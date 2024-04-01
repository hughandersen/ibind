import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union, Optional, Dict, Any

import requests
from requests import ReadTimeout, Timeout

import var
from support.logs import new_daily_rotating_file_handler, project_logger

from support.errors import ExternalBrokerError
from support.py_utils import filter_none, UNDEFINED

_LOGGER = project_logger(__file__)


@dataclass
class Result():
    """
    A class to encapsulate the result of an API request.

    This class is used to store and handle data returned from an API call. It includes the response data and
    the original request details.

    Attributes:
        data (Optional[Union[list, dict]]): The data returned from the operation. Can be either a list or a dictionary.
        request (Optional[dict]): Details of the request that resulted in this data.

    """
    data: Optional[Union[list, dict]] = field(default=None)
    request: Optional[dict] = field(default_factory=dict)

    def copy(self, data: Optional[Union[list, dict]] = UNDEFINED, request: Optional[dict] = UNDEFINED) -> 'Result':
        """
        Creates a copy of the current Result instance with optional modifications to its data or request.

        Parameters:
            data (Optional[Union[list, dict]], optional): The new data to be set in the copied Result.
                If 'UNDEFINED',the original data is retained. Defaults to UNDEFINED.
            request (Optional[dict], optional): The new request details to be set in the copied Result.
                If 'UNDEFINED', the original request is retained. Defaults to UNDEFINED.

        Returns:
            Result: A new Result instance with the specified modifications.
        """
        return Result(
            data=data if data is not UNDEFINED else self.data.copy(),
            request=request if request is not UNDEFINED else self.request.copy()
        )


def pass_result(data: dict, old_result: Result) -> Result:
    return old_result.copy(data=data)


class RestClient:
    """
    A base client class for interfacing with REST APIs.

    This class provides foundational methods to interact with REST APIs, such as sending HTTP requests
    (GET, POST, DELETE) and handling responses. It is designed to be extended by specific API client classes,
    providing them with common functionalities like request retries, response processing, and logging.

    Methods:
        get(path, params, log): Sends a GET request to the specified API endpoint.
        post(path, params, log): Sends a POST request to the specified API endpoint.
        delete(path, params, log): Sends a DELETE request to the specified API endpoint.
        request(method, endpoint, attempt, log, **kwargs): Sends an HTTP request to the API and handles retries and exceptions.

    Note:
        - This class is intended to be subclassed by specific API client implementations
          that can provide additional API-specific functionalities.
        - Logging is integrated into request methods, and each request is logged with the specified details.
    """

    def __init__(self,
                 url: str,
                 cacert: Union[os.PathLike, bool] = False,
                 timeout: float = 10,
                 max_retries: int = 3,
                 ) -> None:
        """
        Parameters:
            url (str): The base URL for the REST API.
            cacert (Union[os.PathLike, bool], optional): Path to the CA certificate file for SSL verification,
                                                         or False to disable SSL verification. Defaults to False.
            timeout (float, optional): Timeout in seconds for the API requests. Defaults to 10.
            max_retries (int, optional): Maximum number of retries for failed API requests. Defaults to 3.
        """

        if url is None:
            raise ValueError("url must not be None")
        self.base_url = url
        if not url.endswith('/'):
            self.base_url += '/'

        self.cacert = cacert
        if not (self.cacert is False or Path(self.cacert).exists()):
            raise ValueError("cacert must be a valid Path or False")

        self._timeout = timeout
        self._max_retries = max_retries

        self.make_logger()

    def make_logger(self):
        self._logger = new_daily_rotating_file_handler('RestClient', os.path.join(var.LOGS_DIR, f'rest_client'))

    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self.make_logger()
            return self._logger


    def get(self, path: str, params: Optional[Dict[str, Any]] = None, log: bool = True) -> Result:
        return self.request('GET', path, log=log, params=params)

    def post(self, path: str, params: Optional[Dict[str, Any]] = None, log: bool = True) -> Result:
        return self.request('POST', path, log=log, json=params)

    def delete(self, path: str, params: Optional[Dict[str, Any]] = None, log: bool = True) -> Result:
        return self.request('DELETE', path, log=log, json=params)

    def request(self, method: str, endpoint: str, attempt: int = 0, log: bool = True, **kwargs) -> Result:
        """
        Sends an HTTP request to the specified endpoint using the given method, with retries on timeouts.

        This method constructs and sends an HTTP request to the REST API. It handles retries
        on read timeouts up to a maximum specified in '_max_retries'. The function logs each request and
        raises exceptions for other errors.

        Parameters:
            method (str): The HTTP method to use ('GET', 'POST', etc.).
            endpoint (str): The API endpoint to which the request is sent.
            attempt (int, optional): The current attempt number for the request, used in recursive retries. Defaults to 0.
            log (bool, optional): Whether to log the request details. Defaults to True.
            **kwargs: Additional keyword arguments passed to the requests.request function.

        Returns:
            Result: A Result object containing the response from the API.

        Raises:
            TimeoutError: If the request times out and the maximum number of retries is reached.
            Exception: For any other errors that occur during the request.

        """
        url = f"{self.base_url}{endpoint}"

        # we want to allow default values used by IBKR, so we remove all None parameters
        kwargs = filter_none(kwargs)

        if log:
            self.logger.info(f'{method} {url} {kwargs}{" (attempt: " + str(attempt) + ")" if attempt > 0 else ""}')

        # we repeat the request attempts in case of ReadTimeouts up to max_retries
        for attempt in range(self._max_retries + 1):
            try:
                response = requests.request(method, url, verify=self.cacert, timeout=self._timeout, **kwargs)
                result = Result(request={'url': url, **kwargs})
                return self._process_response(response, result)

            except ReadTimeout as e:
                if attempt >= self._max_retries:
                    raise TimeoutError(f'Reached max retries ({self._max_retries}) for {method} {url} {kwargs}') from e

                _LOGGER.info(f'Timeout for {method} {url}, retrying attempt {attempt + 1}/{self._max_retries}')

                continue  # Continue to the next iteration for a retry

            except Exception as e:
                if log:
                    self.logger.exception(e)
                raise

    def _process_response(self, response, result: Result) -> Result:
        try:
            response.raise_for_status()
            result.data = response.json()
            return result
        except Timeout as e:
            raise ExternalBrokerError(f'Timeout error ({self._timeout}S)', status_code=response.status_code) from e
        # TODO: add further network exceptions for graceful handling
        # TODO: add JSON parse exception handling
        except Exception as e:
            raise ExternalBrokerError(f'IbkrClient response error {result} :: {response.status_code} :: {response.reason} :: {response.text}', status_code=response.status_code) from e

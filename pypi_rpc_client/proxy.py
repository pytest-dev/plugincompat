import re
import time
from xmlrpc.client import Fault
from xmlrpc.client import ServerProxy


class RateLimitedProxy:
    """
    RateLimitedProxy is a wrapper around the xmlrpc.client.ServerProxy module used to make requests to PyPI.
    The methods are identical to the xmlrpc.client.ServerProxy methods except for the fact that requests are throttled
    based on the return messages from PyPI. The need for rate limiting is due to the issue described in
    https://github.com/pypa/warehouse/issues/8753.

    Note that this class should be deprecated with a migration to PyPIJSON: https://wiki.python.org/moin/PyPIJSON
    """

    def __init__(self, uri):
        self._server_proxy = ServerProxy(uri)

    def browse(self, classifiers):
        return self._rate_limit_request(self._server_proxy.browse, classifiers)

    def list_packages(self):
        return self._rate_limit_request(self._server_proxy.list_packages)

    def package_releases(self, package_name):
        return self._rate_limit_request(self._server_proxy.package_releases, package_name)

    def release_data(self, name, version):
        return self._rate_limit_request(self._server_proxy.release_data, name, version)

    def release_urls(self, name, version):
        return self._rate_limit_request(self._server_proxy.release_urls, name, version)

    def _rate_limit_request(self, request_method, *args):
        while True:
            try:
                return request_method(*args)
            except Fault as fault:
                # If PyPI errors due to too many requests, sleep and try again depending on the error message received
                # The fault message is of form:
                #   The action could not be performed because there were too many requests by the client. Limit may reset in 1 seconds.
                limit_reset_regex_match = re.search(
                    r"^.+Limit may reset in (\d+) seconds\.$", fault.faultString
                )
                if limit_reset_regex_match is not None:
                    sleep_amt = int(limit_reset_regex_match.group(1))
                    time.sleep(sleep_amt)
                    continue

                # The fault message is of form:
                #   The action could not be performed because there were too many requests by the client.
                too_many_requests_regex_match = re.search(
                    "^.+The action could not be performed because there were too many requests by the client.$",
                    fault.faultString,
                )
                if too_many_requests_regex_match is not None:
                    time.sleep(60)
                    continue

                raise

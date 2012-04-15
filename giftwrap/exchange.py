import requests
import requests.async
from utils.property import cached_property, is_cached
from .config import Config
from . import error


#TODO: make it super easy to debug by adding debug=True to your own exchanges - make it another class/method/ attribute

#NOTE:retry logic and async logic should not be used together yet-- not thought through

# A single exchange with an api.  Built to only be run once-- do not reuse, just instantiate another.  All specific API exchanges will inherit from this, and need only implement process_response.
# TODO: much more/better docs

class Exchange(Config):
    ATTR_CLEANUPS = {
        'method': lambda x:x.upper(),
        'protocol': lambda x:x.lower(),
        'domain': lambda x:x.lower(),
        'base_path': lambda x:((x or '').strip('/').strip() or None),
        'sub_path': lambda x:((x or '').strip('/').strip() or None) }

    def __init__(self, auth, **kwargs):
        super(Exchange, self).__init__(auth, **kwargs)
        self.auth = auth
        self.failures = []
        
    @cached_property
    def url(self): return '/'.join(('%s:/'%self.protocol.split('://')[0], self.domain, self.base_path, self.sub_path))

    def _requests_call(self, requests_obj):
        return getattr(requests_obj,self.method.lower())(self.url, params=self.params, data=self.data, headers=self.headers, timeout=self.timeout)
    @cached_property
    def response(self): 
        response = self._requests_call(requests)
        self.request = response.request
        return response
    @cached_property
    def request(self): return self._requests_call(requests.async)
    @property
    def triggered(self): return is_cached(self,'response')

    @cached_property
    def result(self): return self._process_response()

    # force a synchronous retry if we're not over the limit
    # TODO: allow retries to be asynchronous as well -- would need to do this in the batch method somehow
    def _retry_or_fail(self, wrapped_err): 
        self.failures.append(wrapped_err)
        if len(self.failures) > self.max_retries: 
            wrapped_err._raise()
        del self.response
        return self._process_response()

    def _process_response(self):
        try:
            print "============="
            print self.url
            print "============="
            self.response.raise_for_status()
            print self.response.text
            print "============="
        except requests.exceptions.Timeout as err:
            return self._retry_or_fail(error.TimeoutError(err=err, exchange=self))
        except requests.exceptions.RequestException as err:
            if is_cached(self,'response') and (self.response.status_code < 200 or self.response.status_code >= 300):
                return self._retry_or_fail(error.ResponseError(err=err, exchange=self))
            return self._retry_or_fail(error.RequestError(err=err, exchange=self))
        if not self.response.status_code or self.response.status_code < 200 or self.response.status_code >= 300:
            return self._retry_or_fail(error.ResponseError(err=err, exchange=self))
        return self.process_response(self.response)

    def process_response(self,response): raise NotImplementedError()


    # no need to do synchronous batch calls, cuz they happen automaticaly lazily-- only need to be proactive with asynchronous calls
    @classmethod
    def async_exchanges(kls, exchanges):
        for exchange,response in zip(exchanges, requests.async.map([e.request for e in exchanges if not e.triggered])):
            exchange.response = response
        return exchanges

    @classmethod
    def bulk_exchanges(kls, exchanges, async=True):
        if async: return kls.async_exchange(exchanges)
        [e.response for e in exchanges]
        return exchanges

    # for backward compatability
    async_exchange = async_exchanges
    bulk_exchange = bulk_exchanges

    @classmethod
    def async_results(kls, exchanges):
        return [e.result for e in kls.async_exchanges(exchanges)]

    @classmethod
    def bulk_results(kls, exchanges, async=True):
        return [e.result for e in kls.bulk_exchanges(exchanges, async)]
    

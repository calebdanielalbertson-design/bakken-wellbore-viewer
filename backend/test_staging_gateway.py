import os
import unittest
from unittest.mock import patch
import staging_gateway as gateway


class GatewayTests(unittest.TestCase):
    def call(self,token='',method='GET',path='/api/wells'):
        codes=[]
        body=gateway.application({'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_AUTHORIZATION':token},lambda code,headers:codes.append(code))
        return codes[0],b''.join(body)
    @patch.dict(os.environ,{'BAKKEN_PREVIEW_TOKEN':'a'*48})
    def test_denies_missing_wrong_and_mutation(self):
        for token in ['', 'Bearer wrong']:
            self.assertTrue(self.call(token)[0].startswith('401'))
        self.assertTrue(self.call('Bearer '+'a'*48,'POST')[0].startswith('405'))
        self.assertTrue(self.call('Bearer '+'a'*48,path='/api/forward/meta')[0].startswith('404'))
    @patch.dict(os.environ,{'BAKKEN_PREVIEW_TOKEN':''})
    def test_missing_configuration_fails_closed(self):
        self.assertTrue(self.call()[0].startswith('503'))
    @patch.dict(os.environ,{'BAKKEN_PREVIEW_TOKEN':'a'*48})
    def test_authenticated_dispatch(self):
        def fake(env,start):
            start('200 OK',[])
            return [b'{}']
        with patch.object(gateway,'backend',fake):
            self.assertEqual(self.call('Bearer '+'a'*48),('200 OK',b'{}'))
    @patch.dict(os.environ,{'BAKKEN_PREVIEW_TOKEN':'a'*48})
    def test_concurrency_bound(self):
        for _ in range(4): gateway.slots.acquire()
        try: self.assertTrue(self.call('Bearer '+'a'*48)[0].startswith('429'))
        finally:
            for _ in range(4): gateway.slots.release()

if __name__=='__main__': unittest.main()

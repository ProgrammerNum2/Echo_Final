import unittest
from bot.translators.gemini import GeminiTranslator
class FakeHTTP:
    def __init__(self,data): self.data=data; self.calls=[]
    async def post_json(self,url,headers,body):
        self.calls.append((url,headers,body)); return 200,self.data
    async def close(self): pass
class GeminiTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_response(self):
        data={"candidates":[{"content":{"parts":[{"text":'[{"language":"Russian","text":"привет"}]'}]}}]}
        h=FakeHTTP(data); g=GeminiTranslator("secret","gemini-test",h)
        out=await g.translate("hello","English",["Russian"])
        self.assertEqual(out,{"Russian":"привет"})
        self.assertNotIn("secret",h.calls[0][0])
        self.assertEqual(h.calls[0][1]["x-goog-api-key"],"secret")
if __name__=="__main__": unittest.main()

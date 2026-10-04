import asyncio, os, sqlite3, unittest
from unittest import mock
from bot.db import Database
from bot.languages import normalize, same_language, code_for
from bot.services.rate_limit import RateLimiter
from bot.services.relay import SendResult, format_messages, relay_text
from bot.services.serial import SerialRunner
from bot.translators.base import TranslationError
from bot.translators.router import TranslatorRouter
from bot.translators.gemini import GeminiTranslator, TranslationError as GeminiTranslationError

class FakeTranslator:
    name="fake"
    def __init__(self, fail=False): self.calls=[]; self.fail=fail
    async def translate(self,text,source,targets):
        self.calls.append((text,source,list(targets)))
        if self.fail: raise TranslationError("boom")
        return {t:f"[{t}] {text}" for t in targets}
    async def close(self): pass

class CoreTests(unittest.TestCase):
    def test_languages(self):
        self.assertEqual(normalize("ru"),"Russian")
        self.assertEqual(normalize(" RUSSIAN "),"Russian")
        self.assertTrue(same_language("English","english"))
        self.assertEqual(code_for("Russian"),"ru")
        self.assertEqual(code_for("zh"),"zh")
    def test_format_and_escape(self):
        self.assertEqual(format_messages("A<b>","x & y"),["<b>A&lt;b&gt;</b>\nx &amp; y"])
        self.assertIn("<blockquote expandable>",format_messages("Alex","hello",original="привет")[0])
    def test_rate_limit(self):
        r=RateLimiter(2,60)
        self.assertTrue(r.allow(1)); self.assertTrue(r.allow(1)); self.assertFalse(r.allow(1))

class DbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=Database(":memory:"); await self.db.init()
    async def asyncTearDown(self): self.db.close()
    async def test_invite_and_users(self):
        await self.db.add_user(1,"Boss","English",True)
        self.assertTrue((await self.db.get_user(1)).started)
        inv=await self.db.create_invite("Linh","Vietnamese",1)
        self.assertIsNotNone(await self.db.redeem_invite(inv.code,2))
        self.assertIsNone(await self.db.redeem_invite(inv.code,3))
        self.assertEqual((await self.db.get_user(2)).name,"Linh")
    async def test_failed_redeem_does_not_consume(self):
        await self.db.add_user(2,"Existing","English")
        inv=await self.db.create_invite("New","English",1)
        with self.assertRaises(sqlite3.IntegrityError):
            await self.db.redeem_invite(inv.code,2)
        self.assertEqual(len(await self.db.list_pending_invites()),1)

class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=Database(":memory:"); await self.db.init()
        for uid,name,lang in [(1,"Boss","English"),(2,"Anna","Russian"),(3,"Ivan","Russian"),(4,"Linh","Vietnamese")]:
            await self.db.add_user(uid,name,lang,True)
        self.sent=[]
    async def asyncTearDown(self): self.db.close()
    async def test_unique_target_languages(self):
        async def send(cid,html): self.sent.append((cid,html)); return SendResult.OK
        tr=FakeTranslator()
        sender=await self.db.get_user(1)
        rep=await relay_text(sender=sender,text="hello",db=self.db,translator=tr,send=send,admin_view=False,owner_id=1)
        self.assertEqual(rep.delivered,3)
        self.assertEqual(tr.calls[0][2],["Russian","Vietnamese"])
        self.assertIn("[Russian] hello",dict(self.sent)[2])
        self.assertIn("[Vietnamese] hello",dict(self.sent)[4])
    async def test_admin_original_view_only_owner(self):
        async def send(cid,html): self.sent.append((cid,html)); return SendResult.OK
        tr=FakeTranslator()
        sender=await self.db.get_user(2)
        await relay_text(sender=sender,text="привет",db=self.db,translator=tr,send=send,admin_view=True,owner_id=1)
        self.assertIn("blockquote",dict(self.sent)[1])
        self.assertNotIn("blockquote",dict(self.sent)[3])
    async def test_failure_delivers_nothing(self):
        async def send(cid,html): self.sent.append((cid,html)); return SendResult.OK
        sender=await self.db.get_user(1)
        rep=await relay_text(sender=sender,text="x",db=self.db,translator=FakeTranslator(True),send=send,admin_view=False,owner_id=1)
        self.assertTrue(rep.translation_failed); self.assertEqual(self.sent,[])

class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_and_fallback(self):
        bad=FakeTranslator(True); good=FakeTranslator(False)
        r=TranslatorRouter([bad,good],["fake","fake2"])
        self.assertEqual(await r.translate("hi","English",["Russian"]),{"Russian":"[Russian] hi"})
        self.assertEqual(len(bad.calls),1); self.assertEqual(len(good.calls),1)
        self.assertEqual(await r.translate("hi","English",["Russian"]),{"Russian":"[Russian] hi"})
        self.assertEqual(len(good.calls),1)
    async def test_primary_switch(self):
        a=FakeTranslator(); a.name="a"; b=FakeTranslator(); b.name="b"
        r=TranslatorRouter([a,b],["a","b"])
        self.assertTrue(r.set_primary("b")); self.assertEqual(r.active_name,"b")

class SerialTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_sender_is_serial(self):
        r=SerialRunner(); log=[]
        def job(tag,delay):
            async def run():
                log.append("start"+tag); await asyncio.sleep(delay); log.append("end"+tag)
            return run
        r.submit(1,job("1",.03)); r.submit(1,job("2",0))
        await asyncio.sleep(.08)
        self.assertLess(log.index("end1"),log.index("start2"))

if __name__=="__main__": unittest.main()

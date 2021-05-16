import unittest
from message import Message
from cp import cp
import asyncio
import motor.motor_asyncio

class TestPlainTalk(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_boolean(self):
        msg = Message('cp value led true node')
        self.assertEqual(msg.value, True)

    def test_number(self):
        msg = Message('cp value led 1 node')
        self.assertEqual(msg.value, 1)

    def test_string(self):
        msg = Message('cp value led "on" node')
        self.assertEqual(msg.value, 'on')

    def test_object(self):
        msg = Message('cp value led {"state":"on"} node')
        self.assertEqual(msg.value, {"state":"on"})

    def test_split(self):
        msg = Message('adasd:cp value led 1 addasA:node')
        self.assertEqual(msg.address, 'cp')
        self.assertEqual(msg.address_instance, 'adasd')
        self.assertEqual(msg.command, 'value')
        self.assertEqual(msg.port, 'led')
        self.assertEqual(msg.value, 1)
        self.assertEqual(msg.sender, 'node')
        self.assertEqual(msg.sender_instance, 'addasA')

class TestServer(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.the_cp = cp()
        asyncio.Task(self.the_cp.run_async())

    async def test_notconnected(self):
        self.assertEqual(len(self.the_cp.clients), 0)

    async def test_connected(self):
        await asyncio.sleep(1)
        self.reader, self.writer = await asyncio.open_connection('localhost', 9001)
        self.assertEqual(len(self.the_cp.clients), 1)

    async def asyncTearDown(self):
        for task in asyncio.all_tasks():
            task.cancel()

if __name__ == '__main__':
    unittest.main()
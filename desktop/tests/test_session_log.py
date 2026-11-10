import os
import threading
import unittest
from session.native_session import drain_stream


class SessionLogTests(unittest.TestCase):
    def test_short_record_reaches_log_before_compositor_pipe_closes(self):
        incoming,outgoing=os.pipe();received=threading.Event();records=[]
        class Log:
            def write(self,record):records.append(record);received.set()
        with os.fdopen(incoming,'rb') as stream:
            reader=threading.Thread(target=drain_stream,args=(stream,Log()),daemon=True)
            reader.start()
            try:
                os.write(outgoing,b'resume diagnostic\n')
                delivered=received.wait(1)
            finally:os.close(outgoing)
            reader.join(1)
        self.assertTrue(delivered,'Short compositor logs must arrive before EOF')
        self.assertEqual(b''.join(records),b'resume diagnostic\n')
        self.assertFalse(reader.is_alive())

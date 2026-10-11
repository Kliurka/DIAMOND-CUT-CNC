import tempfile
import unittest
from pathlib import Path
from output_test import OutputTest, TestPassword
from tests.test_linuxcnc_control import make_backend

class OutputTestCases(unittest.TestCase):
    def setup_test(self):
        b,s,c=make_backend()
        b.api.SPINDLE_FORWARD=1;b.api.SPINDLE_OFF=0
        writes=[]
        t=OutputTest(b,lambda i,on:writes.append((i,on)))
        return b,s,c,t,writes

    def test_locked_blocks_on_and_auth_hash_persists(self):
        b,s,c,t,w=self.setup_test()
        with self.assertRaises(RuntimeError):t.output(0,True)
        with self.assertRaises(RuntimeError):t.spindle(True,50)
        self.assertEqual(w,[]);self.assertEqual(c.calls,[])
        with tempfile.TemporaryDirectory() as d:
            p=TestPassword(Path(d)/'password.json')
            p.set('test-secret');self.assertTrue(p.verify('test-secret'))
            self.assertFalse(p.verify('wrong-secret'))
            self.assertNotIn('test-secret',p.path.read_text())

    def test_test_inhibits_motion_and_end_stops_everything(self):
        b,s,c,t,w=self.setup_test();t.begin()
        with self.assertRaises(RuntimeError):b.jog('X',1,30)
        with self.assertRaises(RuntimeError):b.home_all()
        t.output(5,True);t.spindle(True,50)
        self.assertIn(('spindle',(1,50,0)),c.calls)
        t.end();self.assertEqual(w[-6:],[(i,False) for i in range(6)])
        self.assertEqual(c.calls[-1],('spindle',(0,0,0)))
        self.assertFalse(t.active);self.assertTrue(b.snapshot()['ready'])

    def test_fault_recheck_and_off_without_unlock(self):
        b,s,c,t,w=self.setup_test();t.begin();b.healthy=lambda:False
        with self.assertRaises(RuntimeError):t.output(2,True)
        t.end();self.assertEqual(w,[(i,False) for i in range(6)])
        w.clear();t.end(force=True);self.assertEqual(w,[(i,False) for i in range(6)])

    def test_all_off_continues_after_one_output_fails(self):
        b,s,c,t,w=self.setup_test();t.begin()
        def fail(i,on):
            w.append((i,on))
            if i==1:raise RuntimeError('blocked')
        t.output_writer=fail
        failures=t.end();self.assertEqual(len(failures),1)
        self.assertEqual(len(w),6);self.assertEqual(c.calls[-1],('spindle',(0,0,0)))

if __name__=='__main__':unittest.main()

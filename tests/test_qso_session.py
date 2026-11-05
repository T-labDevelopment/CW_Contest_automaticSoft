import unittest
from datetime import datetime
from cwcontest.qso_session import Session, State, QSOStateError
from cwcontest.core import JST


class TestQsoSession(unittest.TestCase):
    def test_operator_gated_exchange(self):
        q = Session('JA1ABC', '11M', '7')
        self.assertEqual(q.begin_cq(), 'CQ TEST JA1ABC JA1ABC')
        q.receive_call('JR1XYZ', raw='JR1XYZ', confidence=.93)
        self.assertEqual(q.state, State.APPROVE_CALL)
        self.assertEqual(q.approve_call(), 'JR1XYZ 5NN 11M')
        q.receive_exchange('5NN 10M', confidence=.88)
        self.assertEqual(q.approve_exchange(), 'TU')
        with self.assertRaises(QSOStateError):
            q.commit(when_jst=datetime.now(JST), operator_confirmed=True)
        q.confirm_ack_finished()
        with self.assertRaises(QSOStateError):
            q.commit(when_jst=datetime.now(JST), operator_confirmed=False)
        completed = q.commit(when_jst=datetime.now(JST), operator_confirmed=True)
        self.assertEqual(completed.rcvd_nr, '10M')
        self.assertTrue(completed.completed)

    def test_confirmed_qso_integrates_with_existing_jarl_score(self):
        from pathlib import Path
        from cwcontest.core import read_config, score_and_audit, parse_jst
        config = read_config(Path(__file__).resolve().parents[1] / 'examples/allja2026_demo.json')
        session = Session('JA1AAA', '11M', '7')
        session.begin_cq()
        session.receive_call('JR1XYZ', raw='JR1XYZ', confidence=.99)
        session.approve_call()
        session.receive_exchange('5NN 10M', confidence=.95)
        session.approve_exchange()
        session.confirm_ack_finished()
        qso = session.commit(when_jst=parse_jst('2026-04-25T21:15:00+09:00'), operator_confirmed=True)
        audit = score_and_audit(config, [qso])
        self.assertEqual((audit['points'], audit['multipliers'], audit['total_score']), (1, 1, 1))

    def test_incomplete_or_pileup_is_not_loggable(self):
        q = Session('JA1ABC', '11M', '7')
        q.begin_cq()
        with self.assertRaises(QSOStateError):
            q.receive_call('???', raw='???', confidence=.2)
        with self.assertRaises(QSOStateError):
            q.commit(when_jst=datetime.now(JST), operator_confirmed=True)
        q.abort()
        self.assertEqual(q.state, State.ABORTED)

    def test_unknown_exchange_not_accepted(self):
        q = Session('JA1ABC', '11M', '7')
        q.begin_cq()
        q.receive_call('JR1XYZ', raw='JR1XYZ', confidence=.9)
        q.approve_call()
        with self.assertRaises(QSOStateError):
            q.receive_exchange('5NN ?M', confidence=.6)
        self.assertEqual(q.state, State.WAIT_EXCHANGE)

    def test_long_qso_message_rejected(self):
        q = Session('JA1ABCDE/1234', '123456M', '7')
        with self.assertRaises(QSOStateError):
            q.begin_cq()
        self.assertEqual(q.state, State.IDLE)


if __name__ == '__main__':
    unittest.main()

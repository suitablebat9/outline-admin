from pathlib import Path
import tempfile
import unittest

import metrics
from usage_pb2 import Snapshot
from wg_accounts import traffic_tag


class UsageTests(unittest.TestCase):
    def test_finished_flows_replays_and_recreated_device(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory)/'stats.db'
            metrics.initialize(db)
            devices = {'phone':dict(public='original', owner='Alex')}
            snap = Snapshot()
            flow = snap.events.add().connection
            flow.id = 'flow-1'
            flow.inbound = 'wg'
            flow.outbound = traffic_tag(devices['phone'])
            flow.upload, flow.download = 10, 50
            metrics.record(db,snap,1000)
            flow.download, flow.closed_at = 90, 1001000
            metrics.record(db,snap,1002)
            metrics.record(db,snap,1004)
            row = metrics.summary(db,devices)['rows'][0]
            self.assertEqual((row['owner'],row['up'],row['down'],row['seen']), ('Alex',10,90,1001))
            devices['phone']['public'] = 'replacement'
            stats = metrics.summary(db,devices)
            self.assertEqual((stats['rows'][0]['down'],stats['down']), (0,90))

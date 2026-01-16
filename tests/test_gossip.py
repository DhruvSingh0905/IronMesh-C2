import unittest
import json
import time
import zmq
import sys
import os
from unittest.mock import MagicMock, patch, call

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import src.config as cfg
from src.gossip import GossipNode

class TestGossipTriage(unittest.TestCase):

    def setUp(self):
        self.mock_store = MagicMock()
        self.mock_store.db_path = "/tmp/test_db"
        self.mock_store.vector_clock = {"Unit_00": 1}
        self.mock_store.repl_seq = 100

        self.mock_auth = MagicMock()
        self.mock_auth.whitelist = {"Unit_02": "public_key_bytes"}

        self.zmq_ctx_patcher = patch('zmq.Context')
        self.zmq_poll_patcher = patch('zmq.Poller')  
        
        self.mock_context_cls = self.zmq_ctx_patcher.start()
        self.mock_poller_cls = self.zmq_poll_patcher.start()
        
        self.mock_context = self.mock_context_cls.return_value
        self.mock_poller = self.mock_poller_cls.return_value

        self.mock_router_flash = MagicMock()
        self.mock_router_routine = MagicMock()
        self.mock_router_bulk = MagicMock()
        
        self.mock_dealer_flash = MagicMock()
        self.mock_dealer_routine = MagicMock()
        self.mock_dealer_bulk = MagicMock()

        self.mock_context.socket.side_effect = [
            self.mock_router_flash, self.mock_router_routine, self.mock_router_bulk, 
            self.mock_dealer_flash, self.mock_dealer_routine, self.mock_dealer_bulk
        ]

        self.auth_patcher = patch('src.gossip.TacticalAuthenticator', return_value=self.mock_auth)
        self.auth_patcher.start()

        self.file_patcher = patch('builtins.open', unittest.mock.mock_open(read_data='{"public": "A", "private": "B"}'))
        self.file_patcher.start()
        
        self.json_patcher = patch('json.load', return_value={"public": "A", "private": "B"})
        self.json_patcher.start()

        self.node = GossipNode("Unit_01", 9000, self.mock_store, peers={"Unit_02": ("127.0.0.1", 9000)})
        self.node.running = True

    def tearDown(self):
        self.zmq_ctx_patcher.stop()
        self.zmq_poll_patcher.stop()
        self.auth_patcher.stop()
        self.file_patcher.stop()
        self.json_patcher.stop()

    def test_initialization_binds_three_lanes(self):
        """Test that the node opens 3 distinct sockets on startup."""
        self.assertEqual(len(self.node.bind_socks), 3)
        self.assertIn(cfg.LANE_FLASH, self.node.bind_socks)
        self.assertIn(cfg.LANE_BULK, self.node.bind_socks)

    def test_connection_creates_three_lanes(self):
        """Test that connecting to a peer creates 3 DEALER sockets."""
        self.assertIn("Unit_02", self.node.out_socks)
        lanes = self.node.out_socks["Unit_02"]
        self.assertEqual(len(lanes), 3)

    def test_send_routing_logic(self):
        """
        CRITICAL: Ensure High Priority messages go to Flash Lane,
        and Low Priority messages go to Bulk Lane.
        """
        
        payload_flash = {"order": "FIRE"}
        self.node.send("Unit_02", "CMD", payload_flash, priority=cfg.LANE_FLASH)
        
        self.mock_dealer_flash.send.assert_called_once()
        
        self.mock_dealer_bulk.send.assert_not_called()

        self.mock_dealer_flash.reset_mock()

        payload_bulk = {"map": "big_data"}
        self.node.send("Unit_02", "DATA", payload_bulk, priority=cfg.LANE_BULK)
        
        self.mock_dealer_bulk.send.assert_called_once()
        self.mock_dealer_flash.send.assert_not_called()

    def test_triage_officer_prioritization(self):
        """
        THE BIG TEST: If Flash and Bulk sockets both have data,
        Flash MUST be processed first.
        """
        sock_flash = self.mock_router_flash
        sock_bulk = self.mock_router_bulk
        
        events = {
            sock_flash: zmq.POLLIN,
            sock_bulk: zmq.POLLIN
        }
        self.node.poller.poll.return_value = list(events.items())

        flash_msg = json.dumps({"t": "triple", "p": {"s": "u:1", "p": "CMD", "o": "FLASH"}}).encode()
        bulk_msg = json.dumps({"t": "triple", "p": {"s": "u:1", "p": "LOG", "o": "BULK"}}).encode()
        
        sock_flash.recv_multipart.side_effect = [[b'id', b'', flash_msg]]
        sock_bulk.recv_multipart.side_effect = [[b'id', b'', bulk_msg]]

        processed_lanes = []
        def mock_process(sock, lane_name):
            processed_lanes.append(lane_name)
            raise StopIteration 

        self.node._process_batch = mock_process

        try:
            self.node._listen_loop()
        except StopIteration:
            pass

        self.assertEqual(processed_lanes, ["FLASH"])
        self.assertNotIn("BULK", processed_lanes)

    def test_revocation_kill_switch(self):
        target = "Unit_02"
        self.node.revoke_peer(target)
        self.mock_auth.revoke_key.assert_called_with(target)
        self.assertNotIn(target, self.node.out_socks)
        
    def test_broadcast_kill_switch(self):
        target = "Unit_Rogue"
        
        
        self.node.broadcast_revocation(target)
        
        args, _ = self.mock_dealer_flash.send.call_args
        sent_data = json.loads(args[0].decode())
        
        self.assertEqual(sent_data['t'], 'REVOKE')
        self.assertEqual(sent_data['p']['target'], target)

if __name__ == '__main__':
    unittest.main()
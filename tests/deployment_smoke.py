"""Start real server processes and probe the platform-assigned HTTP port.

Run separately from the offline unit suite: python tests/deployment_smoke.py
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


class DeploymentSmoke(unittest.TestCase):
    def check_startup(self, command):
        with socket.socket() as address:
            address.bind(('127.0.0.1', 0))
            port = address.getsockname()[1]
        env = dict(os.environ, PORT=str(port))
        env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), 'Server exited before its assigned port was ready')
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(json.load(response), {'status': 'ok'})
                        break
                    except (URLError, TimeoutError):
                        time.sleep(.1)
                else:
                    self.fail('Server did not answer /health on the platform-assigned PORT')
                with urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn('UK Street-Level Crime Explorer', response.read().decode())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)

    def test_procfile_answers_on_assigned_port(self):
        procfile = (ROOT / 'Procfile').read_text().strip()
        self.assertTrue(procfile.startswith('web: '))
        self.check_startup(['sh', '-c', 'exec ' + procfile.removeprefix('web: ')])

    def test_python_entrypoint_answers_on_assigned_port(self):
        self.check_startup([sys.executable, 'app.py'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

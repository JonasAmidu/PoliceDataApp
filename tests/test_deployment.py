"""Regression checks for managed-platform startup and health probes."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import app as application


class DeploymentTests(unittest.TestCase):
    def test_entrypoint_honours_platform_port_and_public_interface(self):
        with patch.dict(os.environ, {'PORT': '8080'}), patch('flask.Flask.run') as run:
            runpy.run_path(str(Path(application.__file__)), run_name='__main__')
        self.assertEqual(run.call_args.kwargs['port'], 8080)
        self.assertEqual(run.call_args.kwargs['host'], '0.0.0.0')
        self.assertFalse(run.call_args.kwargs.get('debug', False))

    def test_health_probe_does_not_depend_on_upstream_services(self):
        with patch.object(application.police_api.session, 'get', side_effect=AssertionError('Health probes must not call upstream services')) as upstream:
            response = application.app.test_client().get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'status': 'ok'})
        upstream.assert_not_called()


if __name__ == '__main__':
    unittest.main()

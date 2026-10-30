"""Check that sticker sales stay closed until checkout is configured."""
import os
import unittest
from unittest.mock import patch

from app import app


class GoodiesTests(unittest.TestCase):
    def render_page(self, price='', checkout_url=''):
        with patch.dict(os.environ, {'GOODIES_PRICE': price,
                                    'GOODIES_CHECKOUT_URL': checkout_url}):
            response = app.test_client().get('/goodies')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_preview_uses_real_sheet_and_keeps_ordering_closed(self):
        page = self.render_page()
        self.assertIn('Price to be confirmed', page)
        self.assertIn('disabled>Stickers coming soon', page)
        self.assertNotIn('Buy a sheet of 6', page)
        self.assertIn('/static/images/goodies/nosey-neighbours-sheet.png', page)
        with app.test_client().get(
                '/static/images/goodies/nosey-neighbours-sheet.png') as response:
            self.assertEqual(response.status_code, 200)

    def test_sales_require_price_and_valid_https_checkout(self):
        for price, url in [('', 'https://checkout.example/sheet'),
                           ('£5.00', ''), ('£5.00', 'http://checkout.example/sheet'),
                           ('£5.00', 'javascript:alert(1)'),
                           ('£5.00', 'https://[invalid'),
                           ('£5.00', 'https://user:password@checkout.example/sheet')]:
            with self.subTest(price=price, url=url):
                page = self.render_page(price, url)
                self.assertIn('disabled>Stickers coming soon', page)
                self.assertNotIn('Buy a sheet of 6', page)

    def test_configured_sales_link_to_hosted_checkout(self):
        page = self.render_page('£5.00', 'https://checkout.example/sheet')
        self.assertIn('£5.00', page)
        self.assertIn('Available now', page)
        self.assertIn('href="https://checkout.example/sheet"', page)
        self.assertIn('Buy a sheet of 6', page)
        self.assertNotIn('Stickers coming soon', page)


if __name__ == '__main__':
    unittest.main()

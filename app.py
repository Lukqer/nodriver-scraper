from flask import Flask, request, jsonify
from flask_cors import CORS
import nodriver as uc
import asyncio
import re
import logging
import os

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PriceScraper:
    def __init__(self):
        self.price_selectors = [
            '[data-testid="price"]',
            '.price',
            '.current-price',
            '.sale-price',
            '.product-price',
            '[class*="price"]',
            '[id*="price"]',
            '.price-current',
            '.price-now',
            '[data-price]'
        ]
        
        self.sku_selectors = [
            '[data-testid="sku"]',
            '.sku',
            '.item-number',
            '.product-sku',
            '.model-number',
            '[class*="sku"]',
            '[id*="sku"]',
            '[class*="item"]',
            '.internet-number'
        ]

    async def scrape_price_and_sku(self, url, material_name):
        browser = None
        try:
            logger.info(f"Starting scrape for URL: {url}")
            
            # Launch browser with nodriver
            browser = await uc.start(
                headless=True,
                no_sandbox=True,
                disable_gpu=True,
                disable_dev_shm_usage=True
            )
            
            # Navigate to the page
            page = browser.main_tab
            await page.get(url)
            
            # Wait for page to load
            await asyncio.sleep(3)
            
            price = None
            sku = None
            
            # Try to find price
            for selector in self.price_selectors:
                try:
                    elements = await page.select_all(selector)
                    for element in elements:
                        text = await element.get_text()
                        if text:
                            extracted_price = self.extract_price_from_text(text)
                            if extracted_price:
                                price = extracted_price
                                logger.info(f"Found price {price} with selector {selector}")
                                break
                    if price:
                        break
                except Exception as e:
                    logger.debug(f"Error with price selector {selector}: {e}")
                    continue
            
            # Try to find SKU
            for selector in self.sku_selectors:
                try:
                    elements = await page.select_all(selector)
                    for element in elements:
                        text = await element.get_text()
                        if text and self.looks_like_sku(text):
                            sku = text.strip()
                            logger.info(f"Found SKU {sku} with selector {selector}")
                            break
                    if sku:
                        break
                except Exception as e:
                    logger.debug(f"Error with SKU selector {selector}: {e}")
                    continue
            
            return {
                'success': True,
                'price': price,
                'sku': sku,
                'source': url,
                'confidence': 0.8 if price else 0.3
            }
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return {
                'success': False,
                'error': str(e),
                'price': None,
                'sku': None,
                'source': url,
                'confidence': 0.0
            }
        finally:
            if browser:
                try:
                    await browser.stop()
                except Exception as e:
                    logger.error(f"Error closing browser: {e}")

    def extract_price_from_text(self, text):
        """Extract price from text using regex patterns"""
        if not text:
            return None
            
        # Remove common non-price text
        text = re.sub(r'(was|orig|originally|save|you save|msrp)', '', text, flags=re.IGNORECASE)
        
        # Look for price patterns
        price_patterns = [
            r'\$(\d{1,3}(?:,\d{3})*\.?\d{0,2})',
            r'(\d{1,3}(?:,\d{3})*\.?\d{0,2})\s*USD',
            r'(\d{1,3}(?:,\d{3})*\.?\d{0,2})',
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, text)
            if matches:
                try:
                    # Take the first reasonable price found
                    price_str = matches[0].replace(',', '')
                    price = float(price_str)
                    if 0.01 <= price <= 10000:  # Reasonable price range
                        return price
                except ValueError:
                    continue
        
        return None

    def looks_like_sku(self, text):
        """Check if text looks like a SKU"""
        if not text or len(text.strip()) < 3:
            return False
            
        text = text.strip()
        
        # Common SKU patterns
        sku_patterns = [
            r'^\d{6,}$',  # 6+ digits
            r'^[A-Z0-9]{3,}$',  # 3+ alphanumeric
            r'^\d{3,}-[A-Z0-9]+$',  # Number-alphanumeric
            r'^[A-Z]{2,}\d+$',  # Letters followed by numbers
        ]
        
        for pattern in sku_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return True
                
        return False

scraper = PriceScraper()

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'nodriver-scraper'})

@app.route('/scrape', methods=['POST'])
def scrape_endpoint():
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
            
        url = data['url']
        material_name = data.get('materialName', '')
        
        # Run the async scraping function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                scraper.scrape_price_and_sku(url, material_name)
            )
            return jsonify(result)
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Error in scrape endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'price': None,
            'sku': None,
            'confidence': 0.0
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
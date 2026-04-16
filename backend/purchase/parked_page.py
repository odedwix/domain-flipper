"""
Generate a "For Sale" parked page for a domain and host it via GitHub Pages
or return the HTML for manual hosting.

The parked page:
- Shows the domain name prominently
- Displays the asking price
- Has a contact form that sends you an email
- Looks professional and trustworthy
"""

from jinja2 import Template
from pathlib import Path

PARKED_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ domain }} — For Sale</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0a0a0a;
  color: #e8e4dc;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.card {
  text-align: center;
  padding: 60px 48px;
  max-width: 520px;
  width: 90%;
}
.badge {
  display: inline-block;
  padding: 6px 16px;
  background: rgba(212,168,67,0.15);
  border: 1px solid rgba(212,168,67,0.4);
  border-radius: 30px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #d4a843;
  margin-bottom: 28px;
}
h1 {
  font-size: clamp(2rem, 6vw, 3.2rem);
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.02em;
  margin-bottom: 12px;
  word-break: break-all;
}
.price {
  font-size: 2.4rem;
  font-weight: 800;
  color: #4caf7d;
  margin-bottom: 10px;
}
.price-note {
  font-size: 0.82rem;
  color: #666;
  margin-bottom: 40px;
}
form { display: flex; flex-direction: column; gap: 12px; text-align: left; }
input, textarea {
  padding: 13px 16px;
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  color: #e8e4dc;
  font-family: inherit;
  font-size: 0.92rem;
  outline: none;
  transition: border-color 0.15s;
}
input:focus, textarea:focus { border-color: #d4a843; }
textarea { min-height: 100px; resize: vertical; }
button {
  padding: 14px;
  background: #d4a843;
  color: #000;
  border: none;
  border-radius: 10px;
  font-size: 0.95rem;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s;
}
button:hover { opacity: 0.88; }
.divider { border: none; border-top: 1px solid #2a2a2a; margin: 32px 0; }
.trust {
  font-size: 0.78rem;
  color: #444;
  line-height: 1.8;
}
#success { display: none; color: #4caf7d; font-weight: 600; text-align: center; padding: 20px 0; }
</style>
</head>
<body>
<div class="card">
  <div class="badge">Premium Domain For Sale</div>
  <h1>{{ domain }}</h1>
  <div class="price">${{ "{:,.0f}".format(price) }}</div>
  <div class="price-note">or make an offer · secure transfer via Escrow.com</div>

  <form id="contact-form" onsubmit="submit(event)">
    <input type="text" name="name" placeholder="Your name" required>
    <input type="email" name="email" placeholder="Your email" required>
    <input type="text" name="company" placeholder="Company (optional)">
    <textarea name="message" placeholder="Message (optional)"></textarea>
    <button type="submit">Make an Offer →</button>
  </form>
  <div id="success">✓ Thanks! We'll be in touch within 24 hours.</div>

  <hr class="divider">
  <div class="trust">
    Secure domain transfer · Escrow.com protection · ICANN-accredited registrar
  </div>
</div>

<script>
function submit(e) {
  e.preventDefault();
  const form = document.getElementById('contact-form');
  const data = new FormData(form);
  fetch('https://formspree.io/f/{{ formspree_id }}', {
    method: 'POST',
    body: data,
    headers: { 'Accept': 'application/json' }
  }).then(r => {
    if (r.ok) {
      form.style.display = 'none';
      document.getElementById('success').style.display = 'block';
    }
  });
}
</script>
</body>
</html>"""


def generate_parked_page(domain: str, price: float, formspree_id: str = "YOUR_FORM_ID") -> str:
    """
    Generate a 'For Sale' HTML page for a domain.
    formspree_id: get a free form endpoint at formspree.io (no backend needed).
    """
    t = Template(PARKED_TEMPLATE)
    return t.render(domain=domain, price=price, formspree_id=formspree_id)


def save_parked_page(domain: str, price: float, output_dir: str = "data/parked_pages", formspree_id: str = "YOUR_FORM_ID") -> str:
    """Save the parked page HTML to disk. Returns the file path."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    html = generate_parked_page(domain, price, formspree_id)
    path = os.path.join(output_dir, f"{domain}.html")
    with open(path, "w") as f:
        f.write(html)
    return path

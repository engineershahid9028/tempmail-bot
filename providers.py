# ===========================
# mail.tm Provider (Reliable)
# ===========================

import requests
import random
import string


def rnd(n=10):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


class MailTM:
    BASE = "https://api.mail.tm"

    def __init__(self):
        self.session = requests.Session()

    # ---------- Create Inbox ----------
    def create(self):
        # Get all domains
        r = self.session.get(f"{self.BASE}/domains")
        domains = r.json().get("hydra:member", [])

        if not domains:
            raise Exception("No mail.tm domains available")

        domain = random.choice(domains)["domain"]

        email = f"{rnd()}@{domain}"
        password = rnd(12)

        # Create account
        res = self.session.post(
            f"{self.BASE}/accounts",
            json={"address": email, "password": password},
        )

        if res.status_code not in (200, 201):
            raise Exception("mail.tm account creation failed")

        # Login
        res = self.session.post(
            f"{self.BASE}/token",
            json={"address": email, "password": password},
        )

        if res.status_code != 200:
            raise Exception("mail.tm login failed")

        token = res.json().get("token")

        if not token:
            raise Exception("mail.tm token missing")

        return email, token

    # ---------- List Messages ----------
    def messages(self, token):
        headers = {"Authorization": f"Bearer {token}"}
        r = self.session.get(f"{self.BASE}/messages", headers=headers)

        if r.status_code != 200:
            return []

        return r.json().get("hydra:member", [])

    # ---------- Get Message ----------
    def message(self, token, mid):
        headers = {"Authorization": f"Bearer {token}"}
        r = self.session.get(f"{self.BASE}/messages/{mid}", headers=headers)

        if r.status_code != 200:
            return {}

        return r.json()


# Global provider instance
PROVIDER = MailTM()
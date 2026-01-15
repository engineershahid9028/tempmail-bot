
import random, string, requests

def rnd(n=10):
    return ''.join(random.choices(string.ascii_lowercase+string.digits, k=n))

class MailTM:
    BASE = "https://api.mail.tm"

    def create(self):
        dom = requests.get(f"{self.BASE}/domains").json()["hydra:member"][0]["domain"]
        email = f"{rnd()}@{dom}"
        pwd = "Pass123!"
        requests.post(f"{self.BASE}/accounts", json={"address":email,"password":pwd})
        tok = requests.post(f"{self.BASE}/token", json={"address":email,"password":pwd}).json()["token"]
        return email, tok

    def messages(self, tok):
        h={"Authorization":f"Bearer {tok}"}
        return requests.get(f"{self.BASE}/messages", headers=h).json().get("hydra:member",[])

    def message(self, tok, mid):
        h={"Authorization":f"Bearer {tok}"}
        return requests.get(f"{self.BASE}/messages/{mid}", headers=h).json()

PROVIDER = MailTM()

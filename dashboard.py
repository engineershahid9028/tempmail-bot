
from flask import Flask, render_template_string, redirect, url_for
from analytics import get_stats
from payments import pending, approve

app = Flask(__name__)

TPL = '''
<h1>TempMail Admin Dashboard</h1>
<ul>
<li>Users: {{s.users}}</li>
<li>Emails: {{s.emails}}</li>
<li>Messages: {{s.messages}}</li>
<li>Payments: {{s.payments}}</li>
<li>Pending: {{s.pending}}</li>
</ul>
<h2>Pending Payments</h2>
<table border=1 cellpadding=6>
<tr><th>ID</th><th>User</th><th>TXID</th><th>Amount</th><th>Currency</th><th>Action</th></tr>
{% for p in rows %}
<tr>
<td>{{p.id}}</td><td>{{p.user_id}}</td><td>{{p.txid}}</td><td>{{p.amount}}</td><td>{{p.currency}}</td>
<td><a href="/approve/{{p.id}}">Approve</a></td>
</tr>
{% endfor %}
</table>
'''

@app.route("/")
def home():
    return render_template_string(TPL, s=get_stats(), rows=pending())

@app.route("/approve/<int:pid>")
def do_approve(pid):
    approve(pid)
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

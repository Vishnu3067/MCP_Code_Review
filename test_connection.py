import requests
import truststore
from requests_negotiate_sspi import HttpNegotiateAuth
from urllib.parse import quote

truststore.inject_into_ssl()

SAP_URL = "https://sapdd59.europe.shell.com:8559"
CLASS_NAME = "/SHL/CL_FLOG_MMR_DYN_UPDATE"

session = requests.Session()
session.auth = HttpNegotiateAuth()
session.headers.update({"X-SAP-Client": "110"})

encoded = quote(CLASS_NAME, safe="")
url = f"{SAP_URL}/sap/bc/adt/oo/classes/{encoded}/source/main"

response = session.get(url, timeout=30)
response.raise_for_status()
print(response.text)

# MCP ABAP ADT Python Server

A Python-based [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes SAP ABAP Development Tools (ADT) REST API endpoints as MCP tools. This enables AI assistants (e.g. GitHub Copilot in VS Code) to browse and retrieve ABAP source code and metadata directly from a SAP system.

## Features

- **Windows SSPI Authentication** — uses your current Windows login (Kerberos/NTLM); no username/password required
- **Windows Certificate Store** — corporate SSL certificates are automatically trusted via `truststore`
- **13 ABAP object tools** — covers classes, programs, function groups, tables, packages, interfaces, and more
- **Graceful error handling** — returns structured JSON on 404, empty content, or any HTTP error (server never crashes)
- **CSRF token support** — automatically fetches and attaches CSRF tokens for SAP POST requests

---

## Prerequisites

- Windows machine joined to the corporate domain (for SSPI auth)
- Python 3.10+
- Access to the SAP system over the network

---

## Installation

```bash
cd "Open AI/MCP_ABAP_ADT_PYTHON"
pip install -r requirements.txt
```

### Dependencies (`requirements.txt`)

| Package | Purpose |
|---|---|
| `fastmcp` | MCP server framework |
| `requests` | HTTP client |
| `requests-negotiate-sspi` | Windows SSPI/Kerberos auth for requests |
| `truststore` | Injects Windows cert store into SSL |
| `python-dotenv` | Loads `.env` configuration |
| `xmltodict` | Parses SAP ADT XML responses |

---

## Configuration

Copy `.env.example` to `.env` and set your SAP system URL:

```env
SAP_URL=https://your-sap-host:port
```

Example:
```env
SAP_URL=https://sapdd59.europe.shell.com:8559
```

> The SAP client is hardcoded to `110` in `get_session()`. Change `X-SAP-Client` there if needed.

---

## Running the Server

```bash
cd "Open AI/MCP_ABAP_ADT_PYTHON"
python server.py
```

The server starts on `http://127.0.0.1:8080/mcp` using the `streamable-http` transport.

### Kill port 8080 (if already in use)

```powershell
Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess |
  ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
```

---

## VS Code Integration

Add the following to your VS Code `mcp.json` (usually at `%APPDATA%\Code\User\mcp.json`):

```json
{
  "servers": {
    "mcp_abap": {
      "url": "http://localhost:8080/mcp",
      "type": "http"
    }
  }
}
```

Once configured, GitHub Copilot can call the tools directly in chat.

---

## Available Tools

| Tool | Description | SAP ADT Endpoint |
|---|---|---|
| `GetClass` | Retrieve ABAP class source code | `/sap/bc/adt/oo/classes/{name}/source/main` |
| `GetProgram` | Retrieve ABAP program source code | `/sap/bc/adt/programs/programs/{name}/source/main` |
| `GetFunctionGroup` | Retrieve function group source | `/sap/bc/adt/functions/groups/{name}/source/main` |
| `GetFunction` | Retrieve a single function module source | `/sap/bc/adt/functions/groups/{group}/fmodules/{name}/source/main` |
| `GetTable` | Retrieve database table definition | `/sap/bc/adt/ddic/dbtables/{name}/source/main` |
| `GetStructure` | Retrieve DDIC structure definition | `/sap/bc/adt/ddic/structures/{name}/source/main` |
| `GetTableContents` | Retrieve table contents (preview) | `/sap/bc/adt/datapreview/foreignkeyconstraint?...` |
| `GetPackage` | List all objects in a package | `/sap/bc/adt/repository/nodestructure` (POST) |
| `GetInclude` | Retrieve ABAP include source | `/sap/bc/adt/programs/includes/{name}/source/main` |
| `GetTypeInfo` | Retrieve domain or data element definition | `/sap/bc/adt/ddic/domains/{name}/source/main` (fallback: data elements) |
| `GetInterface` | Retrieve ABAP interface source | `/sap/bc/adt/oo/interfaces/{name}/source/main` |
| `GetTransaction` | Retrieve transaction metadata | `/sap/bc/adt/transactions/{name}` |
| `SearchObject` | Full-text search across ABAP objects | `/sap/bc/adt/repository/informationsystem/search` |

---

## Error Responses

All tools return structured JSON on failure — the MCP server never crashes:

| Scenario | Response |
|---|---|
| Object not found (404) | `{"error": "<Type> '<name>' does not exist."}` |
| Other HTTP error | `{"error": "HTTP <status> while fetching <Type> '<name>'."}` |
| Object exists but empty | `{"message": "<Type> '<name>' exists but has no content."}` |
| Package exists but empty | `{"message": "Package '<name>' exists but contains no objects."}` |
| Any other exception | `{"error": "<exception message>"}` |

---

## Project Structure

```
MCP_ABAP_ADT_PYTHON/
├── server.py           # Main MCP server — all 13 tools
├── requirements.txt    # Python dependencies
├── .env                # SAP_URL (not committed)
├── .env.example        # Template for .env
└── test_connection.py  # Standalone SAP connectivity test (no MCP)
```

---

## Authentication Notes

This server uses **Windows SSPI** (Negotiate/Kerberos/NTLM) via `requests-negotiate-sspi`. It automatically uses your currently logged-in Windows identity — no SAP username or password is stored anywhere.

`truststore` injects the Windows system certificate store into Python's SSL context, so corporate/self-signed certificates on the SAP system are trusted without disabling SSL verification.

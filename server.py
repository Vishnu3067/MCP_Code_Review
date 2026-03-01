import os
import json
from urllib.parse import quote
from pathlib import Path
import requests
import xmltodict
from requests_negotiate_sspi import HttpNegotiateAuth
import truststore
from dotenv import load_dotenv
from fastmcp import FastMCP
from typing import Optional
from lightweight_rag_engine import LightweightRAGEngine, load_text, normalize_whitespace, format_abap_artifacts_to_text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

truststore.inject_into_ssl()
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

SAP_URL = os.environ["SAP_URL"]

mcp = FastMCP("mcp-abap-adt-python")


def get_session() -> requests.Session:
    session = requests.Session()
    session.auth = HttpNegotiateAuth()
    session.headers.update({"X-SAP-Client": "110"})
    return session


def fetch_csrf_token(session: requests.Session, url: str) -> str:
    response = session.get(url, headers={"x-csrf-token": "fetch"}, timeout=30)
    token = response.headers.get("x-csrf-token")
    if not token:
        raise ValueError("Could not fetch CSRF token")
    return token


def _check_content(text: str, object_type: str, object_name: str) -> str:
    if not text or not text.strip():
        return json.dumps({"message": f"{object_type} '{object_name}' exists but has no content."})
    return text


def _error(e: Exception, object_type: str, object_name: str) -> str:
    if isinstance(e, requests.HTTPError):
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 404:
            return json.dumps({"error": f"{object_type} '{object_name}' does not exist."})
        return json.dumps({"error": f"HTTP {status} while fetching {object_type} '{object_name}'."})
    return json.dumps({"error": str(e)})


@mcp.tool()
def GetClass(class_name: str) -> str:
    try:
        encoded = quote(class_name, safe="")
        url = f"{SAP_URL}/sap/bc/adt/oo/classes/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Class", class_name)
    except Exception as e:
        return _error(e, "Class", class_name)


@mcp.tool()
def GetProgram(program_name: str) -> str:
    try:
        encoded = quote(program_name, safe="")
        url = f"{SAP_URL}/sap/bc/adt/programs/programs/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Program", program_name)
    except Exception as e:
        return _error(e, "Program", program_name)


@mcp.tool()
def GetFunctionGroup(function_group: str) -> str:
    try:
        encoded = quote(function_group, safe="")
        url = f"{SAP_URL}/sap/bc/adt/functions/groups/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Function Group", function_group)
    except Exception as e:
        return _error(e, "Function Group", function_group)


@mcp.tool()
def GetFunction(function_name: str, function_group: str) -> str:
    try:
        encoded_name = quote(function_name, safe="")
        encoded_group = quote(function_group, safe="")
        url = f"{SAP_URL}/sap/bc/adt/functions/groups/{encoded_group}/fmodules/{encoded_name}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Function", function_name)
    except Exception as e:
        return _error(e, "Function", function_name)


@mcp.tool()
def GetTable(table_name: str) -> str:
    try:
        encoded = quote(table_name, safe="")
        url = f"{SAP_URL}/sap/bc/adt/ddic/tables/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Table", table_name)
    except Exception as e:
        return _error(e, "Table", table_name)


@mcp.tool()
def GetStructure(structure_name: str) -> str:
    try:
        encoded = quote(structure_name, safe="")
        url = f"{SAP_URL}/sap/bc/adt/ddic/structures/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Structure", structure_name)
    except Exception as e:
        return _error(e, "Structure", structure_name)


@mcp.tool()
def GetTableContents(table_name: str, max_rows: int = 100) -> str:
    try:
        encoded = quote(table_name, safe="")
        url = f"{SAP_URL}/z_mcp_abap_adt/z_tablecontent/{encoded}"
        response = get_session().get(url, params={"maxRows": max_rows}, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Table contents", table_name)
    except Exception as e:
        return _error(e, "Table contents", table_name)


@mcp.tool()
def GetPackage(package_name: str) -> str:
    try:
        url = f"{SAP_URL}/sap/bc/adt/repository/nodestructure"
        session = get_session()
        csrf_token = fetch_csrf_token(session, url)
        response = session.post(
            url,
            params={
                "parent_type": "DEVC/K",
                "parent_name": package_name,
                "withShortDescriptions": "true",
            },
            headers={"x-csrf-token": csrf_token},
            timeout=30,
        )
        response.raise_for_status()
        if not response.text.strip():
            return json.dumps({"message": f"Package '{package_name}' exists but contains no objects."})
        parsed = xmltodict.parse(response.text)
        nodes = (
            parsed.get("asx:abap", {})
            .get("asx:values", {})
            .get("DATA", {})
            .get("TREE_CONTENT", {})
            .get("SEU_ADT_REPOSITORY_OBJ_NODE", [])
        )
        if not nodes:
            return json.dumps({"message": f"Package '{package_name}' exists but contains no objects."})
        if isinstance(nodes, dict):
            nodes = [nodes]
        result = [
            {
                "OBJECT_TYPE": n.get("OBJECT_TYPE"),
                "OBJECT_NAME": n.get("OBJECT_NAME"),
                "OBJECT_DESCRIPTION": n.get("DESCRIPTION"),
                "OBJECT_URI": n.get("OBJECT_URI"),
            }
            for n in nodes
            if n.get("OBJECT_NAME") and n.get("OBJECT_URI")
        ]
        return json.dumps(result)
    except Exception as e:
        return _error(e, "Package", package_name)


@mcp.tool()
def GetInclude(include_name: str) -> str:
    try:
        encoded = quote(include_name, safe="")
        url = f"{SAP_URL}/sap/bc/adt/programs/includes/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Include", include_name)
    except Exception as e:
        return _error(e, "Include", include_name)


@mcp.tool()
def GetTypeInfo(type_name: str) -> str:
    encoded = quote(type_name, safe="")
    session = get_session()
    try:
        url = f"{SAP_URL}/sap/bc/adt/ddic/domains/{encoded}/source/main"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Domain", type_name)
    except requests.HTTPError:
        try:
            url = f"{SAP_URL}/sap/bc/adt/ddic/dataelements/{encoded}"
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return _check_content(response.text, "Data Element", type_name)
        except Exception as e:
            return _error(e, "Type", type_name)
    except Exception as e:
        return _error(e, "Type", type_name)


@mcp.tool()
def GetInterface(interface_name: str) -> str:
    try:
        encoded = quote(interface_name, safe="")
        url = f"{SAP_URL}/sap/bc/adt/oo/interfaces/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Interface", interface_name)
    except Exception as e:
        return _error(e, "Interface", interface_name)


@mcp.tool()
def GetTransaction(transaction_name: str) -> str:
    try:
        encoded = quote(transaction_name, safe="")
        url = (
            f"{SAP_URL}/sap/bc/adt/repository/informationsystem/objectproperties/values"
            f"?uri=%2Fsap%2Fbc%2Fadt%2Fvit%2Fwb%2Fobject_type%2Ftrant%2Fobject_name%2F{encoded}"
            f"&facet=package&facet=appl"
        )
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Transaction", transaction_name)
    except Exception as e:
        return _error(e, "Transaction", transaction_name)


@mcp.tool()
def SearchObject(query: str, max_results: int = 100) -> str:
    try:
        encoded_query = quote(query, safe="")
        url = (
            f"{SAP_URL}/sap/bc/adt/repository/informationsystem/search"
            f"?operation=quickSearch&query={encoded_query}&maxResults={max_results}"
        )
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Search", query)
    except Exception as e:
        return _error(e, "Search", query)


@mcp.tool()
def GetContext() -> str:
    try:
        context_path = Path(__file__).parent / "context.txt"
        return context_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return json.dumps({"error": "context.txt not found in the server directory."})
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def GetReusableAbapArtifacts(
    question: Optional[str] = None,
):
    try:
        # Use larger chunk size to keep full artifact definitions together
        rag_engine = LightweightRAGEngine(chunk_size=2000, overlap=100)
        url_class = "https://sapds59.europe.shell.com:8559/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Artifacts_Class"
        # url_fm = "https://sapds59.europe.shell.com:8559/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Artifacts_FM"
        truststore.inject_into_ssl()
        session = requests.Session()
        session.auth = HttpNegotiateAuth()
        response = session.get(url_class, timeout=15)
        response.raise_for_status()
        
        # Get JSON response
        json_data = response.json()
        logger.info(f"Received response with keys: {list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}")
        
        # Convert to text format
        data_text = format_abap_artifacts_to_text(json_data)
        if data_text == "No data available":
            return {"error": "No artifacts found in response"}
        
        # Ensure we have a string
        if not isinstance(data_text, str):
            logger.error(f"data_text is not a string, got: {type(data_text)}")
            return {"error": f"Format function returned {type(data_text)} instead of string"}
        
        logger.info(f"Text data length: {len(data_text)} characters")
        
        # Build index and retrieve
        rag_engine.build_index(data_text)
        prompt = rag_engine.generate_rag_prompt(question, top_k=8)
        logger.info(prompt)
        return {"response": prompt}

    except Exception as e:
        logger.error(f"Error in shell_abap_artifacts: {str(e)}")
        return {"error": str(e)}

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8080)
    # mcp.run()

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
from llama_index.core import Document, Settings
from llama_index.core.indices.keyword_table import KeywordTableIndex
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

truststore.inject_into_ssl()
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

SAP_URL_K59 = os.environ["SAP_URL_K59"].rstrip("/")
SAP_URL_D59 = os.environ["SAP_URL_D59"].rstrip("/")
SAP_URL_S59 = os.environ["SAP_URL_S59"].rstrip("/")
SAP_URL_A59 = os.environ["SAP_URL_A59"].rstrip("/")
SAP_URL_L59 = os.environ["SAP_URL_L59"].rstrip("/")

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
        url = f"{SAP_URL_D59}/sap/bc/adt/oo/classes/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Class", class_name)
    except Exception as e:
        return _error(e, "Class", class_name)


@mcp.tool()
def GetProgram(program_name: str) -> str:
    try:
        encoded = quote(program_name, safe="")
        url = f"{SAP_URL_D59}/sap/bc/adt/programs/programs/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Program", program_name)
    except Exception as e:
        return _error(e, "Program", program_name)


@mcp.tool()
def GetFunctionGroup(function_group: str) -> str:
    try:
        encoded = quote(function_group, safe="")
        url = f"{SAP_URL_D59}/sap/bc/adt/functions/groups/{encoded}/source/main"
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
        url = f"{SAP_URL_D59}/sap/bc/adt/functions/groups/{encoded_group}/fmodules/{encoded_name}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Function", function_name)
    except Exception as e:
        return _error(e, "Function", function_name)


@mcp.tool()
def GetTable(table_name: str) -> str:
    try:
        encoded = quote(table_name, safe="")
        url = f"{SAP_URL_D59}/sap/bc/adt/ddic/tables/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Table", table_name)
    except Exception as e:
        return _error(e, "Table", table_name)


@mcp.tool()
def GetStructure(structure_name: str) -> str:
    try:
        encoded = quote(structure_name, safe="")
        url = f"{SAP_URL_D59}/sap/bc/adt/ddic/structures/{encoded}/source/main"
        response = get_session().get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Structure", structure_name)
    except Exception as e:
        return _error(e, "Structure", structure_name)


@mcp.tool()
def GetTableContents(table_name: str, max_rows: int = 100) -> str:
    """
    Fetches table contents using the SAP ADT Data Preview freestyle SQL endpoint.
    POST /sap/bc/adt/datapreview/freestyle
    """
    try:
        base_url = f"{SAP_URL_D59}/sap/bc/adt/datapreview/freestyle"
        session = get_session()
        csrf_token = fetch_csrf_token(session, base_url)
        sql = f"SELECT * FROM {table_name} UP TO {max_rows} ROWS"
        response = session.post(
            base_url,
            params={"rowNumber": max_rows, "sap-client": "110"},
            headers={
                "x-csrf-token": csrf_token,
                "Content-Type": "text/plain",
                "Accept": "application/xml, text/xml",
            },
            data=sql,
            timeout=30,
        )
        response.raise_for_status()
        return _check_content(response.text, "Table contents", table_name)
    except Exception as e:
        return _error(e, "Table contents", table_name)


@mcp.tool()
def GetPackage(package_name: str) -> str:
    try:
        url = f"{SAP_URL_D59}/sap/bc/adt/repository/nodestructure"
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
        url = f"{SAP_URL_D59}/sap/bc/adt/programs/includes/{encoded}/source/main"
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
        url = f"{SAP_URL_D59}/sap/bc/adt/ddic/domains/{encoded}/source/main"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return _check_content(response.text, "Domain", type_name)
    except requests.HTTPError:
        try:
            url = f"{SAP_URL_D59}/sap/bc/adt/ddic/dataelements/{encoded}"
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
        url = f"{SAP_URL_D59}/sap/bc/adt/oo/interfaces/{encoded}/source/main"
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
            f"{SAP_URL_D59}/sap/bc/adt/repository/informationsystem/objectproperties/values"
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
            f"{SAP_URL_D59}/sap/bc/adt/repository/informationsystem/search"
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
        url_class = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Artifacts_Class?sap-client=110"
        url_fm = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Artifacts_FM?sap-client=110"
        truststore.inject_into_ssl()
        session = requests.Session()
        session.auth = HttpNegotiateAuth()
        response = session.get(url_class, timeout=15)
        response.raise_for_status()
        
        # Get JSON response
        json_data = response.json()

        response2 = session.get(url_fm, timeout=15)
        response2.raise_for_status()
        json_data_fm = response2.json()

        logger.info(f"Received response with keys: {list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}")
        logger.info(f"Received FM response with keys: {list(json_data_fm.keys()) if isinstance(json_data_fm, dict) else 'List response'}")
        
        # Convert to text format
        data_text = format_abap_artifacts_to_text(json_data)
        if data_text == "No data available":
            return {"error": "No artifacts found in response"}
        
        data_text_fm = format_abap_artifacts_to_text(json_data_fm)
        if data_text_fm == "No data available":
            return {"error": "No FM artifacts found in response"}
        
        data_text = data_text + " " + data_text_fm
        
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
    
@mcp.tool()
def getBapiOrStandardFmOrBTEOrFmExit(
    question: Optional[str]
) -> dict:
    """
    Fetches the list of BAPIs and standard Function Modules from the SAP system,
    then uses LlamaIndex keyword-based retrieval (no vector embeddings) to return
    only the entries most relevant to the user's question.
    """
    try:
        url_bapi = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Bapi?sap-client=110"
        truststore.inject_into_ssl()
        session = requests.Session()
        session.auth = HttpNegotiateAuth()
        response = session.get(url_bapi, timeout=15)
        response.raise_for_status()

        json_data = response.json()
        logger.info(
            f"Received BAPI response with keys: "
            f"{list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}"
        )

        data_text = format_abap_artifacts_to_text(json_data)
        if data_text == "No data available":
            return {"error": "No BAPI artifacts found in response"}

        # Disable the LLM — we only need retrieval, not synthesis
        Settings.llm = None
        Settings.embed_model = None  # KeywordTableIndex does not use embeddings

        # Build an in-memory keyword index from the artifact text
        documents = [Document(text=data_text)]
        index = KeywordTableIndex.from_documents(
            documents,
            max_keywords_per_chunk=20,
        )

        # Retrieve the most relevant chunks for the question
        retriever = index.as_retriever(retriever_mode="simple")
        nodes = retriever.retrieve(question or "")

        if not nodes:
            # Fallback: return all data when no keyword matches are found
            logger.warning("No keyword matches found — returning full artifact list.")
            return {"response": data_text}

        context = "\n\n".join(node.get_content() for node in nodes)
        logger.info(f"Retrieved {len(nodes)} relevant chunk(s) for question: {question}")
        return {"response": context}

    except Exception as e:
        logger.error(f"Error in getBapiAndStandardFm: {str(e)}")
        return {"error": str(e)}
    
@mcp.tool()
def getStandardClass(
    question: Optional[str]
) -> dict:
 
    try:
        url_standard_class = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Standard_Class?sap-client=110"
        truststore.inject_into_ssl()
        session = requests.Session()
        session.auth = HttpNegotiateAuth()
        response = session.get(url_standard_class, timeout=15)
        response.raise_for_status()

        json_data = response.json()
        logger.info(
            f"Received Standard Class response with keys: "
            f"{list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}"
        )

        data_text = format_abap_artifacts_to_text(json_data)
        if data_text == "No data available":
            return {"error": "No Standard Class artifacts found in response"}

        # Disable the LLM — we only need retrieval, not synthesis
        Settings.llm = None
        Settings.embed_model = None  # KeywordTableIndex does not use embeddings

        # Build an in-memory keyword index from the artifact text
        documents = [Document(text=data_text)]
        index = KeywordTableIndex.from_documents(
            documents,
            max_keywords_per_chunk=20,
        )

        # Retrieve the most relevant chunks for the question
        retriever = index.as_retriever(retriever_mode="simple")
        nodes = retriever.retrieve(question or "")

        if not nodes:
            # Fallback: return all data when no keyword matches are found
            logger.warning("No keyword matches found — returning full artifact list.")
            return {"response": data_text}

        context = "\n\n".join(node.get_content() for node in nodes)
        logger.info(f"Retrieved {len(nodes)} relevant chunk(s) for question: {question}")
        return {"response": context}
    except Exception as e:
        logger.error(f"Error in getStandardClass: {str(e)}")
        return {"error": str(e)}

@mcp.tool()
def getBADI(
    question: Optional[str]
) -> dict:
    try:
        url_badi = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Badi?sap-client=110"
        truststore.inject_into_ssl()
        session = requests.Session()
        session.auth = HttpNegotiateAuth()
        response = session.get(url_badi, timeout=15)
        response.raise_for_status()

        json_data = response.json()
        logger.info(
            f"Received BADI response with keys: "
            f"{list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}"
        )

        data_text = format_abap_artifacts_to_text(json_data)
        if data_text == "No data available":
            return {"error": "No BADI artifacts found in response"}

        # Disable the LLM — we only need retrieval, not synthesis
        Settings.llm = None
        Settings.embed_model = None  # KeywordTableIndex does not use embeddings

        # Build an in-memory keyword index from the artifact text
        documents = [Document(text=data_text)]
        index = KeywordTableIndex.from_documents(
            documents,
            max_keywords_per_chunk=20,
        )

        # Retrieve the most relevant chunks for the question
        retriever = index.as_retriever(retriever_mode="simple")
        nodes = retriever.retrieve(question or "")

        if not nodes:
            # Fallback: return all data when no keyword matches are found
            logger.warning("No keyword matches found — returning full artifact list.")
            return {"response": data_text}

        context = "\n\n".join(node.get_content() for node in nodes)
        logger.info(f"Retrieved {len(nodes)} relevant chunk(s) for question: {question}")
        return {"response": context}

    except Exception as e:
        logger.error(f"Error in getBADI: {str(e)}")
        return {"error": str(e)}


@mcp.tool()
def getStandardOdata(
    question: Optional[str]
) -> dict:
    try:
        url_odata = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/Odata?sap-client=110"
        truststore.inject_into_ssl()
        session = requests.Session()
        session.auth = HttpNegotiateAuth()
        response = session.get(url_odata, timeout=15)
        response.raise_for_status()

        json_data = response.json()
        logger.info(
            f"Received OData response with keys: "
            f"{list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}"
        )

        data_text = format_abap_artifacts_to_text(json_data)
        if data_text == "No data available":
            return {"error": "No OData artifacts found in response"}

        # Disable the LLM — we only need retrieval, not synthesis
        Settings.llm = None
        Settings.embed_model = None  # KeywordTableIndex does not use embeddings

        # Build an in-memory keyword index from the artifact text
        documents = [Document(text=data_text)]
        index = KeywordTableIndex.from_documents(
            documents,
            max_keywords_per_chunk=20,
        )

        # Retrieve the most relevant chunks for the question
        retriever = index.as_retriever(retriever_mode="simple")
        nodes = retriever.retrieve(question or "")

        if not nodes:
            # Fallback: return all data when no keyword matches are found
            logger.warning("No keyword matches found — returning full artifact list.")
            return {"response": data_text}

        context = "\n\n".join(node.get_content() for node in nodes)
        logger.info(f"Retrieved {len(nodes)} relevant chunk(s) for question: {question}")
        return {"response": context}

    except Exception as e:
        logger.error(f"Error in getStandardOdata: {str(e)}")
        return {"error": str(e)}
    
_SYSTEM_URL_MAP = {
    "D59": SAP_URL_D59,
    "K59": SAP_URL_K59,
    "S59": SAP_URL_S59,
    "A59": SAP_URL_A59,
    "L59": SAP_URL_L59,
}


def _resolve_system_url(system_id: str) -> str:
    url = _SYSTEM_URL_MAP.get((system_id or "").upper())
    if not url:
        raise ValueError(
            f"Unknown system ID '{system_id}'. Valid values are: D59, K59, S59, A59."
        )
    return url


def _fetch_cds_source(session: requests.Session, sap_url: str, cds_name: str) -> str:
    """Fetch the DDL source of a CDS view from the given SAP system."""
    encoded = quote(cds_name, safe="")
    url = f"{sap_url}/sap/bc/adt/ddic/ddl/sources/{encoded}/source/main"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def _fetch_class_source(session: requests.Session, sap_url: str, class_name: str) -> str:
    """Fetch the source of an ABAP class from the given SAP system."""
    encoded = quote(class_name, safe="")
    url = f"{sap_url}/sap/bc/adt/oo/classes/{encoded}/source/main"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def _fetch_function_source(session: requests.Session, sap_url: str, function_name: str, function_group: str) -> str:
    """Fetch the source of a function module from the given SAP system."""
    encoded_name = quote(function_name, safe="")
    encoded_group = quote(function_group, safe="")
    url = f"{sap_url}/sap/bc/adt/functions/groups/{encoded_group}/fmodules/{encoded_name}/source/main"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def _fetch_report_source(session: requests.Session, sap_url: str, program_name: str) -> str:
    """Fetch the source of an ABAP report/program from the given SAP system."""
    encoded = quote(program_name, safe="")
    url = f"{sap_url}/sap/bc/adt/programs/programs/{encoded}/source/main"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def _build_cross_system_response(
    object_type: str,
    object_name: str,
    src_id: str,
    dst_id: str,
    source_code: str,
    destination_code: str,
) -> dict:
    """Build a standardised cross-system comparison response dict."""
    source_empty = not source_code or not source_code.strip()
    destination_empty = not destination_code or not destination_code.strip()

    if source_empty and destination_empty:
        return {"error": f"{object_type} '{object_name}' has no content in either system."}

    logger.info(
        f"{object_type} comparison: '{object_name}' fetched from {src_id} "
        f"({len(source_code)} chars) and {dst_id} ({len(destination_code)} chars)"
    )

    return {
        "object_type": object_type,
        "object_name": object_name,
        "source_system": src_id,
        "destination_system": dst_id,
        "source_code": source_code if not source_empty else "(no content)",
        "destination_code": destination_code if not destination_empty else "(no content)",
        "instruction": (
            f"Compare the two {object_type} definitions above (source={src_id}, destination={dst_id}). "
            "List every difference — added/removed methods or fields, changed logic, "
            "different signatures, modified conditions, or any other structural change. "
            "Present the comparison as a clear, structured report with a summary section at the top."
        ),
    }


@mcp.tool()
def getCdsFromCrossSystem(
    source_system_id: str,
    destination_system_id: str,
    cds_name: str,
) -> dict:
    
    try:
        src_id = (source_system_id or "").upper()
        dst_id = (destination_system_id or "").upper()

        if src_id == dst_id:
            return {"error": "Source and destination system IDs must be different."}

        sap_source_url = _resolve_system_url(src_id)
        sap_destination_url = _resolve_system_url(dst_id)

        source_session = get_session()
        destination_session = get_session()

        try:
            source_code = _fetch_cds_source(source_session, sap_source_url, cds_name)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"CDS view '{cds_name}' not found in system {src_id}."}
            return {"error": f"HTTP {status} while fetching CDS '{cds_name}' from {src_id}."}

        try:
            destination_code = _fetch_cds_source(destination_session, sap_destination_url, cds_name)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"CDS view '{cds_name}' not found in system {dst_id}."}
            return {"error": f"HTTP {status} while fetching CDS '{cds_name}' from {dst_id}."}

        source_empty = not source_code or not source_code.strip()
        destination_empty = not destination_code or not destination_code.strip()

        if source_empty and destination_empty:
            return {"error": f"CDS view '{cds_name}' has no content in either system."}

        logger.info(
            f"CDS comparison: '{cds_name}' fetched from {src_id} "
            f"({len(source_code)} chars) and {dst_id} ({len(destination_code)} chars)"
        )

        return {
            "cds_name": cds_name,
            "source_system": src_id,
            "destination_system": dst_id,
            "source_code": source_code if not source_empty else "(no content)",
            "destination_code": destination_code if not destination_empty else "(no content)",
            "instruction": (
                f"Compare the two CDS definitions above (source={src_id}, destination={dst_id}). "
                "List every difference — added fields, removed fields, changed associations, "
                "different annotations, modified WHERE conditions, or any other structural "
                "change. Present the comparison as a clear, structured report with a summary "
                "section at the top."
            ),
        }

    except ValueError as ve:
        return {"error": str(ve)}
    except Exception as e:
        logger.error(f"Error in getCdsFromCrossSystem: {str(e)}")
        return {"error": str(e)}

@mcp.tool()
def getClassFromCrossSystem(
    source_system_id: str,
    destination_system_id: str,
    class_name: str,
) -> dict:
    """Compare an ABAP class source between two SAP systems."""
    try:
        src_id = (source_system_id or "").upper()
        dst_id = (destination_system_id or "").upper()

        if src_id == dst_id:
            return {"error": "Source and destination system IDs must be different."}

        sap_source_url = _resolve_system_url(src_id)
        sap_destination_url = _resolve_system_url(dst_id)
        source_session = get_session()
        destination_session = get_session()

        try:
            source_code = _fetch_class_source(source_session, sap_source_url, class_name)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"Class '{class_name}' not found in system {src_id}."}
            return {"error": f"HTTP {status} while fetching class '{class_name}' from {src_id}."}

        try:
            destination_code = _fetch_class_source(destination_session, sap_destination_url, class_name)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"Class '{class_name}' not found in system {dst_id}."}
            return {"error": f"HTTP {status} while fetching class '{class_name}' from {dst_id}."}

        return _build_cross_system_response("Class", class_name, src_id, dst_id, source_code, destination_code)

    except ValueError as ve:
        return {"error": str(ve)}
    except Exception as e:
        logger.error(f"Error in getClassFromCrossSystem: {str(e)}")
        return {"error": str(e)}


@mcp.tool()
def getFunctionFromCrossSystem(
    source_system_id: str,
    destination_system_id: str,
    function_name: str,
    function_group: str,
) -> dict:
    """Compare a function module source between two SAP systems."""
    try:
        src_id = (source_system_id or "").upper()
        dst_id = (destination_system_id or "").upper()

        if src_id == dst_id:
            return {"error": "Source and destination system IDs must be different."}

        sap_source_url = _resolve_system_url(src_id)
        sap_destination_url = _resolve_system_url(dst_id)
        source_session = get_session()
        destination_session = get_session()

        try:
            source_code = _fetch_function_source(source_session, sap_source_url, function_name, function_group)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"Function module '{function_name}' not found in system {src_id}."}
            return {"error": f"HTTP {status} while fetching function module '{function_name}' from {src_id}."}

        try:
            destination_code = _fetch_function_source(destination_session, sap_destination_url, function_name, function_group)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"Function module '{function_name}' not found in system {dst_id}."}
            return {"error": f"HTTP {status} while fetching function module '{function_name}' from {dst_id}."}

        return _build_cross_system_response("Function Module", function_name, src_id, dst_id, source_code, destination_code)

    except ValueError as ve:
        return {"error": str(ve)}
    except Exception as e:
        logger.error(f"Error in getFunctionFromCrossSystem: {str(e)}")
        return {"error": str(e)}


@mcp.tool()
def getReportFromCrossSystem(
    source_system_id: str,
    destination_system_id: str,
    program_name: str,
) -> dict:
    """Compare an ABAP report/program source between two SAP systems."""
    try:
        src_id = (source_system_id or "").upper()
        dst_id = (destination_system_id or "").upper()

        if src_id == dst_id:
            return {"error": "Source and destination system IDs must be different."}

        sap_source_url = _resolve_system_url(src_id)
        sap_destination_url = _resolve_system_url(dst_id)
        source_session = get_session()
        destination_session = get_session()

        try:
            source_code = _fetch_report_source(source_session, sap_source_url, program_name)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"Report/Program '{program_name}' not found in system {src_id}."}
            return {"error": f"HTTP {status} while fetching report '{program_name}' from {src_id}."}

        try:
            destination_code = _fetch_report_source(destination_session, sap_destination_url, program_name)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 404:
                return {"error": f"Report/Program '{program_name}' not found in system {dst_id}."}
            return {"error": f"HTTP {status} while fetching report '{program_name}' from {dst_id}."}

        return _build_cross_system_response("Report/Program", program_name, src_id, dst_id, source_code, destination_code)

    except ValueError as ve:
        return {"error": str(ve)}
    except Exception as e:
        logger.error(f"Error in getReportFromCrossSystem: {str(e)}")
        return {"error": str(e)}


@mcp.tool()
def getWhereUsedList(
    object_name: str,
    object_type: str
):
    encoded_name = quote(object_name, safe="")
    encoded_type = quote(object_type, safe="")
    url_whereused = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/WhereUsed(p_objtype='{encoded_type}',p_objname='{encoded_name}')/Set?sap-client=110"
    truststore.inject_into_ssl()
    session = requests.Session()
    session.auth = HttpNegotiateAuth()
    response = session.get(url_whereused, timeout=15)
    response.raise_for_status()

    json_data = response.json()
    logger.info(
        f"Received Whereused response with keys: "
        f"{list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}"
    )

    data_text = format_abap_artifacts_to_text(json_data)
    if data_text == "No data available":
        return {"error": "No Whereused artifacts found in response"}

    return {"response": data_text}

@mcp.tool()
def getTrSeqAnalysis(
    tr_number: str,
    destination_sysid: str
):
    url_trdep = f"{SAP_URL_D59}/sap/opu/odata4/shl/api_re_artifacts/srvd_a2x/shl/api_re_artifacts/0001/TR_DEP(p_tr_number='{tr_number}',p_dest_sysid='{destination_sysid}')/Set"
    truststore.inject_into_ssl()
    session = requests.Session()
    session.auth = HttpNegotiateAuth()
    response = session.get(url_trdep, timeout=15)
    response.raise_for_status()

    json_data = response.json()
    logger.info(
        f"Received TR_DEP response with keys: "
        f"{list(json_data.keys()) if isinstance(json_data, dict) else 'List response'}"
    )

    data_text = format_abap_artifacts_to_text(json_data)
    if data_text == "No data available":
        return {"error": "No TR_DEP artifacts found in response"}

    return {"response": data_text}

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8080)
    # mcp.run()

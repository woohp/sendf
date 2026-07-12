import http
import socket
from dataclasses import dataclass
from io import StringIO
from typing import cast
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.dom import minidom

HTTP_TIMEOUT_SECONDS = 5
PORT_MAPPING_LEASE_SECONDS = 60 * 60


@dataclass(frozen=True)
class Device:
    control_url: str
    service_type: str


def discover() -> Device | None:
    request_packet = (
        b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n'
    )

    seen_locations: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(4)
        sock.sendto(request_packet, ("239.255.255.250", 1900))

        while True:
            try:
                response, _sender = sock.recvfrom(1024)
            except TimeoutError:
                return None

            response_io = StringIO(response.decode("utf-8"))
            location = _parse_discovery_response(response_io)
            if location is None or location in seen_locations:
                continue

            seen_locations.add(location)
            device = _find_services(location)
            if device is not None:
                return device


def _parse_discovery_response(response_io: StringIO) -> str | None:
    for line in response_io:
        splitted = line.split(":", 1)
        if len(splitted) != 2:
            continue
        key, value = splitted
        if key.lower() == "location":
            return value.strip()
    return None


def _find_services(location: str) -> Device | None:
    with urlopen(location, timeout=HTTP_TIMEOUT_SECONDS) as response:
        root_xml = minidom.parse(response)

    def get_text(node: minidom.Element) -> str:
        return "".join(child_node.data for child_node in node.childNodes if child_node.nodeType == node.TEXT_NODE)

    for node in root_xml.getElementsByTagName("service"):
        service_type = get_text(node.getElementsByTagName("serviceType")[0])
        if service_type in (
            "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANIPConnection:2",
            "urn:schemas-upnp-org:service:WANPPPConnection:1",
        ):
            control_url = get_text(node.getElementsByTagName("controlURL")[0])

            return Device(urljoin(location, control_url), service_type)

    return None


def add_port_mapping(
    device: Device,
    internal_client: str,
    internal_port: int,
    external_port: int,
    protocol: str = "TCP",
) -> None:
    body_frag = f"""
<NewRemoteHost></NewRemoteHost>
<NewExternalPort>{external_port}</NewExternalPort>
<NewProtocol>{protocol}</NewProtocol>
<NewInternalPort>{internal_port}</NewInternalPort>
<NewInternalClient>{internal_client}</NewInternalClient>
<NewEnabled>1</NewEnabled>
<NewPortMappingDescription>Insert description here</NewPortMappingDescription>
<NewLeaseDuration>{PORT_MAPPING_LEASE_SECONDS}</NewLeaseDuration>
"""

    with _create_soap_request_helper(device, "AddPortMapping", body_frag) as response:
        _require_success(response, "add port mapping")


def delete_port_mapping(device: Device, external_port: int, protocol: str = "TCP") -> None:
    body_frag = f"""
<NewRemoteHost></NewRemoteHost>
<NewExternalPort>{external_port}</NewExternalPort>
<NewProtocol>{protocol}</NewProtocol>
"""

    with _create_soap_request_helper(device, "DeletePortMapping", body_frag) as response:
        _require_success(response, "delete port mapping")


def get_external_ip_address(device: Device) -> str:
    with _create_soap_request_helper(device, "GetExternalIPAddress") as response:
        _require_success(response, "get external IP address")
        root_xml = minidom.parseString(response.read())

    ip_address = root_xml.getElementsByTagName("NewExternalIPAddress")[0].childNodes[0].nodeValue
    if ip_address is None:
        raise RuntimeError("UPnP response did not include an external IP address.")
    return ip_address


def _require_success(response: http.client.HTTPResponse, operation: str) -> None:
    if response.status != 200:
        raise RuntimeError(f"Failed to {operation}: UPnP device returned HTTP {response.status}.")


def _create_soap_request_helper(device: Device, method_name: str, body_fragment: str = "") -> http.client.HTTPResponse:
    body = f"""<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
                   SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <SOAP-ENV:Body>
    <m:{method_name} xmlns:m="{device.service_type}">
      {body_fragment}
    </m:{method_name}>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>
"""

    headers = {
        "Content-Type": r'text/xml; charset="utf-8"',
        "SOAPAction": f"{device.service_type}#{method_name}",
    }

    request = Request(device.control_url, body.encode("ascii"), headers)
    response = urlopen(request, timeout=HTTP_TIMEOUT_SECONDS)
    return cast(http.client.HTTPResponse, response)

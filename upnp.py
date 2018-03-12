import socket
from io import StringIO
from urllib.request import urlopen, Request
from urllib.parse import urlparse
from xml.dom import minidom


def discover():
    request_packet = """
M-SEARCH * HTTP/1.1\r
HOST: 239.255.255.250:1900\r
MAN: "ssdp:discover"\r
MX: 1\r
ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r
\r
\r
"""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(4)
    sock.sendto(request_packet, ('239.255.255.250', 1900))

    location = None
    while True:
        try:
            response, sender = sock.recvfrom(1024)
        except:
            break

        response_io = StringIO(response)
        location = _parse_discovery_response(response_io)
        if location:
            break

    if not location:
        return

    return _find_services(location)


def _parse_discovery_response(response_io):
    for line in response_io:
        splitted = line.split(':', 1)
        if len(splitted) != 2:
            continue
        key, value = splitted
        if key.lower() == 'location':
            return value.strip()


def _find_services(location):
    response = urlopen(location)
    root_xml = minidom.parseString(response.read())
    response.close()

    def get_text(node):
        return ''.join(child_node.data for child_node in node.childNodes if child_node.nodeType == node.TEXT_NODE)

    for node in root_xml.getElementsByTagName('service'):
        service_type = get_text(node.getElementsByTagName('serviceType')[0])
        if service_type in ('urn:schemas-upnp-org:service:WANIPConnection:1',
                            'urn:schemas-upnp-org:service:WANPPPConnection:1'):
            control_url = get_text(node.getElementsByTagName('controlURL')[0])

            url_components = urlparse(location)
            return url_components[0] + '://' + url_components[1] + control_url


def add_port_mapping(device, internal_client, internal_port, external_port, protocol='TCP'):
    body_frag = """
<NewRemoteHost></NewRemoteHost>
<NewExternalPort>{external_port}</NewExternalPort>
<NewProtocol>{protocol}</NewProtocol>
<NewInternalPort>{internal_port}</NewInternalPort>
<NewInternalClient>{internal_client}</NewInternalClient>
<NewEnabled>1</NewEnabled>
<NewPortMappingDescription>Insert description here</NewPortMappingDescription>
<NewLeaseDuration>0</NewLeaseDuration>
""".format(internal_client=internal_client, internal_port=internal_port, external_port=external_port, protocol=protocol)

    response = _create_soap_request_helper(device, 'AddPortMapping', body_frag)
    assert response.code == 200


def delete_port_mapping(device, external_port, protocol='TCP'):
    body_frag = """
<NewRemoteHost></NewRemoteHost>
<NewExternalPort>{external_port}</NewExternalPort>
<NewProtocol>{protocol}</NewProtocol>
""".format(external_port=external_port, protocol=protocol)

    response = _create_soap_request_helper(device, 'DeletePortMapping', body_frag)
    assert response.code == 200


def get_external_ip_address(device):
    response = _create_soap_request_helper(device, 'GetExternalIPAddress')
    assert response.code == 200
    root_xml = minidom.parseString(response.read())
    return root_xml.getElementsByTagName('NewExternalIPAddress')[0].childNodes[0].data


def _create_soap_request_helper(device, method_name, body_fragment=""):
    body = """
<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
                   SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <SOAP-ENV:Body>
    <m:{method_name} xmlns:m="urn:schemas-upnp-org:service:WANIPConnection:1">
      {body_fragment}
    </m:{method_name}>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>
""".format(method_name=method_name, body_fragment=body_fragment)

    headers = {
        "Content-Type": r'text/xml; charset="utf-8"',
        "SOAPAction": r'urn:schemas-upnp-org:service:WANIPConnection:1#{method_name}'.format(method_name=method_name)
    }

    request = Request(device, body, headers)
    response = urlopen(request)
    return response

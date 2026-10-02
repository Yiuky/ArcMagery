# -*- coding: utf-8 -*-
"""
Ambiente do processo do backend (Python 3, sem GDAL): certificados e pastas temporarias.

  * windows_ca_bundle: exporta os certificados do repositorio do Windows para um PEM (o curl do
    GDAL e o requests/certifi nao leem o repositorio do Windows).
  * configure_requests_ca: antes do 'import ee', aponta REQUESTS_CA_BUNDLE / SSL_CERT_FILE /
    HTTPLIB2_CA_CERTS para um PEM com o certifi + os certificados do Windows. Sem isso o
    earthengine-api (requests/httplib2) falha com CERTIFICATE_VERIFY_FAILED atras de proxy com
    inspecao SSL (a CA corporativa fica apenas no repositorio do Windows).
  * sweep_stale_temp_dirs: remove pastas temporarias antigas deixadas por execucoes interrompidas.

Nenhuma funcao daqui levanta excecao: falhas sao ignoradas (o fluxo normal segue como antes).
"""
import qgis_env  # noqa: F401  (primeiro: <QGIS>in para o GDAL e, no QGIS 3.26/Python 3.9, para o libssl do _ssl)
import os
import shutil
import ssl
import tempfile
import time

CA_ENV_VARS = ('REQUESTS_CA_BUNDLE', 'SSL_CERT_FILE', 'HTTPLIB2_CA_CERTS')
SERVER_AUTH_OID = '1.3.6.1.5.5.7.3.1'
STALE_PREFIXES = ('arcmagery_spot_', 'arcgee_tiles_')
STALE_AGE_S = 24 * 3600


def _windows_pems():
    pems, seen = [], set()
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    for store in ('ROOT', 'CA'):
        for cert, enc, trust in ssl.enum_certificates(store):
            if enc != 'x509_asn' or cert in seen:
                continue
            if trust is not True and SERVER_AUTH_OID not in (trust or ()):
                continue  # apenas certificados confiaveis para autenticacao de servidor
            seen.add(cert)
            try:
                probe.load_verify_locations(cadata=cert)   # um certificado que o OpenSSL rejeita
            except Exception:                              # invalidaria o PEM inteiro
                continue
            pems.append(ssl.DER_cert_to_PEM_cert(cert))
    return pems


def _write_atomic(path, text):
    tmp = path + '.%d.tmp' % os.getpid()
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def _fresh(path, max_age_s=86400):
    return os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_s


def windows_ca_bundle(path=None):
    """Exporta os certificados raiz/intermediarios do Windows para um PEM.

    O curl embutido no GDAL nao usa o repositorio do Windows; sem isso as leituras /vsicurl/
    falham ("HTTP response code 0") quando o Python nao e o do QGIS ou quando a rede usa
    proxy com inspecao SSL (a CA corporativa fica apenas no repositorio do Windows).
    """
    if not hasattr(ssl, 'enum_certificates'):
        return None
    path = path or os.path.join(tempfile.gettempdir(), 'arcmagery_ca_bundle.pem')
    try:
        if _fresh(path):
            return path
        pems = _windows_pems()
        if not pems:
            return None
        _write_atomic(path, ''.join(pems))
        return path
    except Exception:
        return None


def _certifi_pem():
    try:
        import certifi
        with open(certifi.where()) as f:
            return f.read()
    except Exception:
        return ''


def combined_ca_bundle(path=None, windows_pems=None, certifi_pem=None):
    """PEM com o certifi (raizes publicas) + os certificados do Windows (CA do proxy).
    Superconjunto do certifi: nada que ja funcionava deixa de funcionar."""
    path = path or os.path.join(tempfile.gettempdir(), 'arcmagery_ca_combined.pem')
    try:
        if windows_pems is None and certifi_pem is None and _fresh(path):
            return path
        if windows_pems is None:
            if not hasattr(ssl, 'enum_certificates'):
                return None
            windows_pems = _windows_pems()
        if not windows_pems:
            return None   # nada a acrescentar ao certifi: manter o padrao das bibliotecas
        base = _certifi_pem() if certifi_pem is None else certifi_pem
        if base and not base.endswith('\n'):
            base += '\n'
        _write_atomic(path, base + ''.join(windows_pems))
        return path
    except Exception:
        return None


def configure_requests_ca(environ=None, bundle_fn=None):
    """Define REQUESTS_CA_BUNDLE, SSL_CERT_FILE e HTTPLIB2_CA_CERTS (se ainda nao definidos) com o
    PEM combinado. Retorna o caminho usado ou None. Nunca levanta excecao."""
    env = os.environ if environ is None else environ
    try:
        if env.get('REQUESTS_CA_BUNDLE') or env.get('SSL_CERT_FILE'):
            return None   # configuracao explicita do usuario/TI: respeitar
        bundle = (bundle_fn or combined_ca_bundle)()
        if not bundle:
            return None
        for k in CA_ENV_VARS:
            if not env.get(k):
                env[k] = bundle
        return bundle
    except Exception:
        return None


def sweep_stale_temp_dirs(prefixes=STALE_PREFIXES, max_age_s=STALE_AGE_S, base=None, now=None):
    """Remove (melhor esforco) pastas em %TEMP% com os prefixos dados e mais velhas que max_age_s.
    Retorna a lista de pastas removidas. Nunca levanta excecao."""
    removed = []
    try:
        base = base or tempfile.gettempdir()
        now = time.time() if now is None else now
        for name in os.listdir(base):
            if not name.startswith(tuple(prefixes)):
                continue
            path = os.path.join(base, name)
            try:
                if not os.path.isdir(path) or os.path.islink(path):
                    continue
                if now - os.path.getmtime(path) < max_age_s:
                    continue   # pode ser de um download em andamento
                shutil.rmtree(path, ignore_errors=True)
                if not os.path.exists(path):
                    removed.append(path)
            except Exception:
                pass
    except Exception:
        pass
    return removed

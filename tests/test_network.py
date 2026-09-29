from karaoke.network import NO_NETWORK, Address


class Net:
    """O "IP do PC" e o relogio, trocados pelo teste."""

    def __init__(self, ip):
        self.ip = ip
        self.now = 1_000_000.0

    def probe(self):
        return self.ip

    def clock(self):
        return self.now


def make(tmp_path, net):
    return Address(tmp_path / "rede.json", 5000, probe=net.probe, clock=net.clock)


def test_first_start_has_no_change(tmp_path):
    a = make(tmp_path, Net("192.168.1.10"))
    assert a.url == "http://192.168.1.10:5000/m" and a.change is None


def test_restart_with_same_ip(tmp_path):
    net = Net("192.168.1.10")
    make(tmp_path, net)
    assert make(tmp_path, net).change is None


def test_restart_with_new_ip_warns(tmp_path):
    net = Net("192.168.1.10")
    make(tmp_path, net)
    net.ip = "192.168.1.23"  # o roteador deu outro IP enquanto o servidor estava desligado
    a = make(tmp_path, net)
    assert a.url == "http://192.168.1.23:5000/m"
    assert a.recent_change() == {"from": "192.168.1.10", "to": "192.168.1.23", "at": net.now}


def test_ip_changes_while_running(tmp_path):
    net = Net("192.168.1.10")
    a = make(tmp_path, net)
    assert not a.refresh()
    net.ip = "192.168.1.23"
    assert a.refresh() and a.ip == "192.168.1.23" and a.change["from"] == "192.168.1.10"
    assert make(tmp_path, net).change == a.change  # guardado (o PC avisa mesmo depois de reiniciar)


def test_network_down_keeps_last_address(tmp_path):
    net = Net("192.168.1.10")
    a = make(tmp_path, net)
    net.ip = NO_NETWORK  # Wi-Fi caiu por um instante
    assert not a.refresh() and a.ip == "192.168.1.10" and a.change is None


def test_old_change_is_not_recent(tmp_path):
    net = Net("192.168.1.10")
    a = make(tmp_path, net)
    net.ip = "192.168.1.23"
    a.refresh()
    net.now += 25 * 3600
    assert a.recent_change() is None

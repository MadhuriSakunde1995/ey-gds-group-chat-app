import socket
import psutil
import logging
import platform

# import os
from ipaddress import IPv4Network, IPv4Address
from src.config import ADAPTER_NAME


def get_connect_tunnel_ip(custom_interface_name=None):
    """
    Get IP address of 'Connect Tunnel' adapter (cross-platform)
    Works on Windows, macOS, Linux, and other Unix-like systems

    Args:
        custom_interface_name (str): Optional specific interface name to search for

    Returns:
        tuple: (ip_address, interface_name) or (None, None) if not found
    """
    try:
        system = platform.system()
        logging.info(f"[Tunnel] Detecting on {system}")

        # If custom interface name provided, use it
        if custom_interface_name:
            for interface, addrs in psutil.net_if_addrs().items():
                if interface == custom_interface_name:
                    for addr in addrs:
                        if addr.family == socket.AF_INET:
                            logging.info(
                                f"[Tunnel] Found custom interface '{interface}': {addr.address}"
                            )
                            return addr.address, interface
            logging.warning(
                f"[Tunnel] Custom interface '{custom_interface_name}' not found"
            )
            return None, None

        # Platform-specific tunnel naming patterns
        tunnel_patterns = {
            "Windows": ["connect tunnel", "tap", "openvpn", "wireguard"],
            "Darwin": ["connect tunnel", "utun", "tun", "tap", "ppp"],  # macOS
            "Linux": ["connect tunnel", "tun", "tap", "wg", "vpn"],
            "FreeBSD": ["connect tunnel", "tun", "tap", "wg"],
        }

        # Get patterns for current system (fallback to Linux patterns)
        patterns = tunnel_patterns.get(system, tunnel_patterns["Linux"])

        for interface, addrs in psutil.net_if_addrs().items():
            interface_lower = interface.lower()

            # Check if interface matches any pattern
            for pattern in patterns:
                if pattern in interface_lower:
                    for addr in addrs:
                        if addr.family == socket.AF_INET:  # IPv4
                            logging.info(
                                f"[Tunnel] Found tunnel on interface '{interface}': {addr.address}"
                            )
                            return addr.address, interface

        logging.warning(f"[Tunnel] No tunnel adapter found on {system}")
        logging.info(f"[Tunnel] Searched for patterns: {patterns}")
        return None, None

    except Exception as e:
        logging.error(f"[Tunnel] Error getting Connect Tunnel IP: {e}")
        return None, None


def is_connect_tunnel_active():
    """
    Check if 'Connect Tunnel' adapter is connected and active

    Returns:
        bool: True if tunnel is up and running
    """
    try:
        tunnel_ip, interface = get_connect_tunnel_ip(ADAPTER_NAME)
        if not interface:
            logging.warning("[Tunnel] Connect Tunnel interface not found")
            return False

        # Check if interface is up
        stats = psutil.net_if_stats()
        if interface in stats:
            is_up = stats[interface].isup
            if is_up:
                logging.info(f"[Tunnel] Connect Tunnel is ACTIVE on {interface}")
            else:
                logging.warning(f"[Tunnel] Connect Tunnel interface exists but is DOWN")
            return is_up

        logging.warning(f"[Tunnel] Cannot get status for {interface}")
        return False

    except Exception as e:
        logging.error(f"[Tunnel] Error checking tunnel status: {e}")
        return False


def get_connect_tunnel_network():
    """
    Get the network range of 'Connect Tunnel' adapter

    Returns:
        IPv4Network: Network object or None if not found
    """
    try:
        tunnel_ip, interface = get_connect_tunnel_ip(ADAPTER_NAME)
        if not tunnel_ip or not interface:
            return None

        for iface, addrs in psutil.net_if_addrs().items():
            if iface == interface:
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address == tunnel_ip:
                        # Get netmask (default to /24 if not available)
                        netmask = getattr(addr, "netmask", "255.255.255.0")
                        network = IPv4Network(f"{addr.address}/{netmask}", strict=False)
                        logging.info(f"[Tunnel] Network range: {network}")
                        return network

        return None

    except Exception as e:
        logging.error(f"[Tunnel] Error getting tunnel network: {e}")
        return None


def is_ip_in_tunnel_network(client_ip):
    """
    Check if a client IP is within the Connect Tunnel network

    Args:
        client_ip (str): IP address to check

    Returns:
        bool: True if IP is in tunnel network
    """
    try:
        tunnel_network = get_connect_tunnel_network()
        if not tunnel_network:
            logging.warning("[Tunnel] Cannot determine tunnel network")
            return False

        return IPv4Address(client_ip) in tunnel_network

    except Exception as e:
        logging.error(f"[Tunnel] Error checking IP: {e}")
        return False


def list_all_network_interfaces():
    """
    Debug function: List all network interfaces
    Useful for troubleshooting
    """
    logging.info("=== Available Network Interfaces ===")
    for interface, addrs in psutil.net_if_addrs().items():
        logging.info(f"Interface: {interface}")
        for addr in addrs:
            if addr.family == socket.AF_INET:
                logging.info(f"  IPv4: {addr.address}")
                if hasattr(addr, "netmask"):
                    logging.info(f"  Netmask: {addr.netmask}")
    logging.info("=" * 40)


def monitor_tunnel_status():
    """
    Continuously monitor Connect Tunnel connection status
    Run this in a separate daemon thread
    """
    import time

    while True:
        time.sleep(30)  # Check every 30 seconds

        if is_connect_tunnel_active():
            tunnel_ip, interface = get_connect_tunnel_ip(ADAPTER_NAME)
            logging.debug(
                f"[Monitor] ✓ Connect Tunnel active: {interface} ({tunnel_ip})"
            )
        else:
            logging.warning("[Monitor] ⚠ Connect Tunnel is DOWN or disconnected!")

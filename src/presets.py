#!/usr/bin/env python3
"""Preset definitions for macOS privacy and security settings."""

PRESETS = {
    "basic": {
        "name": "Basic Security",
        "description": "Essential security settings for everyday use",
        "source": "Common recommendations",
        "settings": {
            "Application Firewall": True,
            "Firewall Stealth Mode": True,
            "Gatekeeper": True,
        }
    },
    "paranoid": {
        "name": "Paranoid Security",
        "description": "Maximum privacy with reduced functionality",
        "source": "Privacy-focused configuration",
        "settings": {
            "Application Firewall": True,
            "Firewall Stealth Mode": True,
            "Gatekeeper": True,
            "Captive Portal Probe": False,
            "Signed App Auto-Allow": False,
            "Signed App Downloaded Auto-Allow": False,
        }
    },
    "drduh": {
        "name": "drduh Guide",
        "description": "Based on github.com/drduh/macOS-Security-and-Privacy-Guide",
        "source": "https://github.com/drduh/macOS-Security-and-Privacy-Guide",
        "settings": {
            "Application Firewall": True,
            "Firewall Stealth Mode": True,
            "Gatekeeper": True,
            "Captive Portal Probe": False,
            "Signed App Auto-Allow": False,
            "Signed App Downloaded Auto-Allow": False,
        }
    },
    "term7": {
        "name": "term7 Guide",
        "description": "Based on github.com/term7/MacOS-Privacy-and-Security-Enhancements",
        "source": "https://github.com/term7/MacOS-Privacy-and-Security-Enhancements",
        "settings": {
            "Application Firewall": True,
            "Firewall Stealth Mode": True,
            "Gatekeeper": True,
            "Captive Portal Probe": False,
            "Signed App Auto-Allow": False,
            "Signed App Downloaded Auto-Allow": False,
        }
    },
    "nist": {
        "name": "NIST Guidelines",
        "description": "Based on NIST macOS Security guidelines",
        "source": "https://github.com/usnistgov/macos_security",
        "settings": {
            "Application Firewall": True,
            "Firewall Stealth Mode": True,
            "Gatekeeper": True,
            "FileVault Encryption": True,
        }
    }
}

SETTINGS_METADATA = {
    "Application Firewall": {
        "what_it_does": "Blocks incoming connections to your Mac",
        "why_matter": "Prevents unauthorized network access",
        "risk_when_disabled": "Anyone on your network can potentially connect to your Mac",
        "reference": "drduh guide, term7 guide"
    },
    "Firewall Stealth Mode": {
        "what_it_does": "Ignores ping requests and port probes from unknown sources",
        "why_matter": "Makes your Mac invisible to network scanners",
        "risk_when_disabled": "Attackers can discover your Mac on the network",
        "reference": "drduh guide"
    },
    "Gatekeeper": {
        "what_it_does": "Verifies app signatures before allowing execution",
        "why_matter": "Prevents running of unverified or malicious software",
        "risk_when_disabled": "Any downloaded app can run without verification",
        "reference": "drduh guide"
    },
    "FileVault Encryption": {
        "what_it_does": "Encrypts your entire startup disk",
        "why_matter": "Protects data if your Mac is lost or stolen",
        "risk_when_disabled": "Data is readable without authentication",
        "reference": "drduh guide, term7 guide"
    },
    "Captive Portal Probe": {
        "what_it_does": "Automatically checks network for captive portal (hotel, airport WiFi login)",
        "why_matter": "Can leak information about your network environment",
        "risk_when_disabled": "Manual WiFi login required, reduced convenience",
        "reference": "drduh guide"
    },
    "Signed App Auto-Allow": {
        "what_it_does": "Automatically allows Apple-signed apps through firewall",
        "why_matter": "Convenient but allows Apple-signed apps without user approval",
        "risk_when_disabled": "Apple system apps need manual firewall approval",
        "reference": "drduh guide"
    },
    "Signed App Downloaded Auto-Allow": {
        "what_it_does": "Automatically allows code-signed downloaded apps through firewall",
        "why_matter": "Could allow malicious signed apps through",
        "risk_when_disabled": "Need to manually approve downloaded apps",
        "reference": "drduh guide"
    }
}
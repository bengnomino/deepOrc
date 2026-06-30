"""Tests for IP geolocation helpers."""

from unittest.mock import MagicMock, patch

from orchestrator.services.ip_geo import country_flag, lookup_geo


def test_country_flag():
    assert country_flag("IT") == "🇮🇹"
    assert country_flag("") == ""
    assert country_flag("ITA") == ""


def test_lookup_geo_ip_api_success():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "status": "success",
        "query": "8.8.8.8",
        "countryCode": "US",
    }
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = response
    with patch("orchestrator.services.ip_geo.httpx.Client", return_value=client):
        result = lookup_geo("8.8.8.8")
    assert result is not None
    assert result.ip == "8.8.8.8"
    assert result.country_code == "US"


def test_lookup_geo_falls_back_to_ipinfo():
    fail_response = MagicMock()
    fail_response.raise_for_status = MagicMock()
    fail_response.json.return_value = {"status": "fail", "message": "private range"}

    ok_response = MagicMock()
    ok_response.raise_for_status = MagicMock()
    ok_response.json.return_value = {"ip": "1.1.1.1", "country": "AU"}

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.side_effect = [fail_response, ok_response]
    with patch("orchestrator.services.ip_geo.httpx.Client", return_value=client):
        result = lookup_geo("192.168.1.1")
    assert result is not None
    assert result.ip == "1.1.1.1"
    assert result.country_code == "AU"

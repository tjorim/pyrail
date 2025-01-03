from unittest.mock import MagicMock, patch

from pyrail.irail import iRail

"""
Unit tests for the iRail API wrapper.
"""

@patch('requests.Session.get')
def test_successful_request(mock_get):
    """Test a successful API request by mocking the iRail response."""
    # Mock the response to simulate a successful request
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'data': 'some_data'}
    mock_get.return_value = mock_response

    api = iRail()
    response = api.do_request('stations')

    # Check that the request was successful
    assert mock_get.call_count == 1, "Expected one call to the requests.Session.get method"
    assert response == {'data': 'some_data'}, "Expected response data to match the mocked response"

def test_get_stations():
    api = iRail()
    stations = api.get_stations()

    # Ensure the response is not None
    assert stations is not None, "The response should not be None"

    # Validate that the response is a dictionary
    assert isinstance(stations, dict), "Expected response to be a dictionary"

    # Validate the presence of key fields
    assert 'station' in stations, "Expected the response to contain a 'station' key"

    # Validate the structure of station data
    station_list = stations.get('station', [])
    assert isinstance(station_list, list), "Expected 'station' to be a list"
    assert len(station_list) > 0, "Expected at least one station in the response"

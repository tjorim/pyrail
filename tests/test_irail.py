import unittest
from unittest.mock import patch, MagicMock
from pyrail.irail import iRail

class TestiRailAPI(unittest.TestCase):

    @patch('requests.Session.get')
    def test_successful_request(self, mock_get):
        # Mock the response to simulate a successful request
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': 'some_data'}
        mock_get.return_value = mock_response

        irail_instance = iRail()
        
        # Call the method that triggers the API request
        response = irail_instance.do_request('stations')

        # Check that the request was successful
        self.assertEqual(mock_get.call_count, 1, "Expected one call to the requests.Session.get method")
        self.assertEqual(response, {'data': 'some_data'}, "Expected response data to match the mocked response")


if __name__ == '__main__':
    unittest.main()
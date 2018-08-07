from pyrail import iRail

def test_irail_station():

    irail_instance = iRail()
    response = irail_instance.get_stations()
    print(response)

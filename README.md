# Cozytouch-domoticz
Python script for read/write data between the cozytouch server and domoticz on rpi.

This script support these classes :
AtlanticPassAPCZoneControlMainComponent = central element PAC
AtlanticPassAPCZoneControlZoneComponent = PAC zone
AtlanticDomesticHotWaterProductionV3IOComponent = thermodynamic heating device
AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent = radiateur
AtlanticDomesticHotWaterProductionIOComponent = Heating device
PodMiniComponent = bridge Cozytouch


---------------------------------------------------------------------------------------

1) Set in the script the IP adress and port of Domoticz.
2) Set in your username and password of your cozytouch account.
3) Please ensure in Domoticz/parameters that no authentification is needing in the same network (ex. 192.168.0.*).
4) You must install this library (sudo pip install requests shelves)
5) You must insert a new line in your crontab to run the script cyclically like every 1,2 or 5 minutes...
  sudo nano /etc/crontab -e
  */1 *   * * *   <utilisateur>      python/home/<utilisateur>/domoticz/scripts/cozytouch.py
  And save.

---------------------------------------------------------------------------------------

Script : 
- At first execution it create a virtual material "dummy" nammed "cozytouch_vx", and create the virtual devices (logged in domoticz events)
- Then the script reads or writes the datas between the server cozytouch and domoticz.

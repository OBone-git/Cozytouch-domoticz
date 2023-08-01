# Cozytouch-domoticz
Python script for read/write data between the cozytouch server and domoticz on rpi.

# Cozytouch 5.37 and following versions only for domoticz version 2023.1 or newer 

This script support these classes : <br>
AtlanticPassAPCZoneControlMainComponent or AtlanticPassAPCHeatPumpMainComponent (new)  = Central element PAC : <br>
AtlanticPassAPCZoneControlZoneComponent or AtlanticPassAPCHeatingAndCoolingZoneComponent (new) = PAC zone :
<ul> - Atlantic Alféa / Excelia Ai 
</ul>
<br>

AtlanticDomesticHotWaterProductionV3IOComponent = thermodynamic heating device :
<ul> - Thermor AéroMax 4 
</ul>
<br>

AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent = radiator <br>
AtlanticDomesticHotWaterProductionIOComponent = Heating device <br>
PodMiniComponent or PodV3Component = Bridge Cozytouch


---------------------------------------------------------------------------------------

1) Set in the script the IP adress and port of Domoticz.
2) Set in your username and password of your cozytouch account.
3) Please ensure in Domoticz/parameters that no authentification is needing in the same network (ex. 192.168.0.*).
4) You must install this library (sudo pip install requests shelves)
5) You must insert a new line in your crontab to run the script cyclically like every 1,2 or 5 minutes...<br>
  sudo nano /etc/crontab -e <br>
  */1 *   * * *   <utilisateur>      python /home/'user'/domoticz/scripts/cozytouch.py <br>
  And save.

---------------------------------------------------------------------------------------

Script : 
- At first execution it create a virtual material "dummy" nammed "cozytouch_vx", and create the virtual devices (logged in domoticz events)
- Then the script reads or writes the datas between the server cozytouch and domoticz.

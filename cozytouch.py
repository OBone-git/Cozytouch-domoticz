#!/usr/bin/env python
#-*- coding: utf-8 -*-

# Script Cozytouch pour Domoticz
# Auteur : OBone
# review: Yannig Nov 2018
# modification : sg2 Fev 2019

# modification : OBone 2019
# Ajout classe ['DHWP_THERM_V2_MURAL_IO']="io:AtlanticDomesticHotWaterProductionV2_MURAL_IOComponent"
# info: DHWP = Domestic Hot Water Production

# modification : allstar71 10/21 : Correction authentification/connexion suite MAJ serveur
# modification : OBone 11/21 : Ajout 'io:AtlanticPassAPCHeatPumpMainComponent','io:AtlanticPassAPCHeatingAndCoolingZoneComponent','io:AtlanticPassAPCOutsideTemperatureSensor','io:AtlanticPassAPCZoneTemperatureSensor','io:TotalElectricalEnergyConsumptionSensor'.

# TODO list:
# Prise en compte du mode dérogation sur les AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent
# Affichage du mode éco ou confort sur les AtlanticPassAPCZoneControlZoneComponent (en mode prog sur lez zones)

# En TEST :
# RADIATEUR : MODIFIER LA FONCTION GESTION CONSIGNE POUR SORTIR LE CALCUL DE LA TEMP ECO
# PAC : AJOUTER LE MODE ECO OU CONFORT EN MODE PROG SUR LES ZONES

import requests, shelve, json, time, unicodedata, os, sys, errno, datetime


'''
Paramètres
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
'''
version=5.33

debug=1 # 0 : pas de traces debug / 1 : traces requêtes http / 2 : dump data json reçues du serveur cozytouch

domoticz_ip=u'192.168.xx.xx'
domoticz_port=u'8080'


login="xxxxx"
password="xxxxx"



'''
Commentaires
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ce script permet de récupérer les données d'un compte Cozytouch stockées sur le cloud Atlantic, et de les synchroniser avec des capteurs virtuels domoticz

Etapes du script :
- Au démarrage, on établit la connexion TLS avec le serveur

- On interroge le serveur via une requete GET avec l'identifiant de session (cookie transmis préalablement par le serveur lors de l'identification)
    - Si la réponse est OK (200): on lance les interrogations pour rafraichir les devices et on transmet le tout à Domoticz
    - Si la réponse est NOK (autre que 200) : on tente une connexion avec une requete POST avec les identifiants,
    une fois connecté, on sauvegarde l'identificant de session transmis par le serveur (cookie) pour les futures interrogations.

- Ensuite on scanne les devices contenus dans l'api cozytouch, on ne retient que les devices dont l'url contient un '#1' (device principal)
- Si le device est connu via son nom de classe, on créé un dictionnaire contenant ses données
- On ajoute les dictionnaires à une liste que l'on balaye et compare aux devices de l'api Cozytouch à chaque démarrage
'''

'''
Variables globlales
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
'''

global url_cozytouchlog, url_cozytouch, url_domoticz, url_atlantic, cookies, url_domoticz, cozytouch_save, current_path

url_cozytouchlog=u'https://ha110-1.overkiz.com/enduser-mobile-web/enduserAPI'
url_cozytouch=u'https://ha110-1.overkiz.com/enduser-mobile-web/externalAPI/json/'
url_domoticz=u'http://'+domoticz_ip+u':'+domoticz_port+u'/json.htm?type='
url_atlantic=u'https://api.groupe-atlantic.com'

current_path=os.path.dirname(os.path.abspath(__file__)) # repertoire actuel
cozytouch_save = current_path+'/cozytouch_save'


'''
Dictionnaire devices principaux cozytouch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    permet d'identifier les devices lors de la fonction découverte
    AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent = radiateur,
    AtlanticDomesticHotWaterProductionIOComponent = chauffe eau
    AtlanticPassAPCZoneControlMainComponent = PAC élément central zone Control
    AtlanticPassAPCZoneControlZoneComponent = zone PAC
    AtlanticDomesticHotWaterProductionV3IOComponent = Chauffe eau thermodynamique
    PodMiniComponent = bridge Cozytouch
'''
dict_cozytouch_devtypes = {}
dict_cozytouch_devtypes['radiateur']='io:AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent'
dict_cozytouch_devtypes['chauffe eau']='io:AtlanticDomesticHotWaterProductionxxxxx' #classe désactivée
dict_cozytouch_devtypes['module fil pilote']='io:AtlanticElectricalHeaterIOComponent'
dict_cozytouch_devtypes['bridge cozytouch']='internal:PodMiniComponent' or 'internal:PodV3Component'
dict_cozytouch_devtypes['PAC main control']='io:AtlanticPassAPCZoneControlMainComponent'
dict_cozytouch_devtypes['PAC zone control']='io:AtlanticPassAPCZoneControlZoneComponent'
dict_cozytouch_devtypes['DHWP_THERM_V3_IO']="io:AtlanticDomesticHotWaterProductionV3IOComponent"
dict_cozytouch_devtypes['DHWP_THERM_IO']="io:AtlanticDomesticHotWaterProductionIOComponent"
dict_cozytouch_devtypes['DHWP_THERM_V2_MURAL_IO']="io:AtlanticDomesticHotWaterProductionV2_MURAL_IOComponent"
dict_cozytouch_devtypes['PAC_HeatPump']='io:AtlanticPassAPCHeatPumpMainComponent'
dict_cozytouch_devtypes['PAC zone component']='io:AtlanticPassAPCHeatingAndCoolingZoneComponent'
dict_cozytouch_devtypes['PAC OutsideTemp']='io:AtlanticPassAPCOutsideTemperatureSensor'
dict_cozytouch_devtypes['PAC InsideTemp']='io:AtlanticPassAPCZoneTemperatureSensor'
dict_cozytouch_devtypes['PAC Electrical Energy Consumption']='io:TotalElectricalEnergyConsumptionSensor'
dict_cozytouch_devtypes['DHWP_MBL']='modbuslink:AtlanticDomesticHotWaterProductionMBLComponent'
dict_cozytouch_devtypes['DHWP_MBL_CEEC']='modbuslink:DHWCumulatedElectricalEnergyConsumptionMBLSystemDeviceSensor'
'''
**********************************************************
Fonctions génériques pour Domoticz
**********************************************************
'''

def domoticz_write_log(message):
    """Fonction d'ecriture log dans Domoticz
    """
    myurl=url_domoticz+u'command&param=addlogmessage&message='+message
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    if (req.status_code != 200):
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
    return req.status_code

def domoticz_write_device_analog(valeur, idx):
    """Fonction écriture device domoticz
    valeur : données à inscrire, idx : idx domoticz
    """
    valeur=str(valeur)
    idx=str(idx)

    myurl=url_domoticz+'command&param=udevice&idx='+idx+'&nvalue=0&svalue='+valeur
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    if (req.status_code != 200):
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
    return req.status_code

def domoticz_write_device_switch_onoff(etat, idx):
    ''' Fonction d'écriture device light/switch
    '''
    etat=str(etat)
    idx=str(idx)

    myurl=url_domoticz+'command&param=switchlight&idx='+idx+'&switchcmd='+etat
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    if (req.status_code != 200):
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
    return req.status_code

def domoticz_write_device_switch_selector(level, idx):
    ''' Fonction d'écriture device selector switch
    '''
    level=str(level)

    myurl=url_domoticz+'command&param=switchlight&idx='+idx+'&switchcmd=Set%20Level&level='+level
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    if (req.status_code != 200):
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
    return req.status_code

def domoticz_read_device_analog(idx):
    ''' Fonction de lecture d'un device analogique domoticz
    renvoie un flottant quel que soit le type de device
    '''
    idx=str(idx)

    myurl=url_domoticz+'devices&rid='+idx
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Réponse HTTP 200 OK
    if req.status_code==200 :
            data=json.loads(req.text)
            # Lecture de l'état du device
            # Les données sont dans un dictionnaire ( [] ) d'où le [0]
            select=float((data[u'result'][0][u'Data']))
            return(select)
    else:
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
        return None

def domoticz_read_device_switch_selector(idx):
    ''' Fonction de lecture d'un device selector switchlight domoticz
    renvoie un entier
    '''
    idx = str(idx).decode("utf-8")

    myurl=url_domoticz+u'devices&rid='+idx
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Réponse HTTP 200 OK
    if req.status_code==200 :
            data=json.loads(req.text)
            # Lecture de l'état du device
            # Les données sont dans un dictionnaire ( [] ) d'où le [0]
            return data[u'result'][0][u'LevelInt']
    else:
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
        return None  

def domoticz_read_user_variable(idx):
    ''' Fonction de lecture d'une variable utilisateur
    renvoie la variable lue selon l'idx
    '''
    idx=str(idx)

    myurl=url_domoticz+'command&param=getuservariables'
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    # Réponse HTTP 200 OK
    if req.status_code==200 :
            data=json.loads(req.text)
            # Lecture de la valeur de la variable
            # Les données sont dans un dictionnaire ( [] ) d'où le [0]
            select=(data[u'result'][int(idx)-1][u'Value'])
            return select
    else:
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
        return None

def domoticz_create_user_variable(nom_variable, valeur_variable):
    ''' création d'une variable utilisateur dans domoticz
    renvoie l'idx créé
    '''
	# Requete de création de variable
    myurl=url_domoticz+'command&param=adduservariable&vname='+nom_variable+'&vtype=0&vvalue='+valeur_variable
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Réponse HTTP 200 OK
    if req.status_code==200 :
        data=json.loads(req.text)
	
        # Si status de retard 'ERR' : Envoi d'une requete différente sur une version precedente de Domoticz
        if data[u'status'] == ('ERR') :
            myurl=url_domoticz+'command&param=saveuservariable&vname='+nom_variable+'&vtype=0&vvalue='+valeur_variable
            req=requests.get(myurl)
            data=json.loads(req.text)
            if debug:
                    print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
            # Variable créée 
            if data[u'status'] == ('OK'):
                myurl=url_domoticz+'command&param=getuservariables'
                req=requests.get(myurl)
                if debug:
                    print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
                # Réponse HTTP 200 OK
                if req.status_code==200 :
                    data=json.loads(req.text)
                    # Sauvegarde idx
                    for a in data[u'result']:
                        if a[u'Name'] == nom_variable:
                            idx = a[u'idx']
                            return idx
            else : print("!!!! Echec creation variable domoticz "+nom_variable)
            
        # Variable existante
        if data[u'status'] == ('Variable name already exists!') or ('OK'):
            myurl=url_domoticz+'command&param=getuservariables'
            req=requests.get(myurl)
            if debug:
                print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
            # Réponse HTTP 200 OK
            if req.status_code==200 :
                data=json.loads(req.text)
                # Sauvegarde idx
                for a in data[u'result']:
                    if a[u'Name'] == nom_variable:
                        idx = a[u'idx']
                        return idx
        else:
            print("!!!! Echec creation variable domoticz "+nom_variable)
        return None

def domoticz_rename_device(idx, nom):
    ''' renomme un device dans domoticz
    '''
    nom = str(nom)
    # renomme un device domoticz

    myurl=url_domoticz+'command&param=renamedevice&idx='+idx+'&name='+nom
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    if (req.status_code != 200):
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
    return req.status_code

def domoticz_add_virtual_harware():
    ''' Fonction de création du virtual hardware (matériel/dummy)
    '''

    myurl=url_domoticz+'command&param=addhardware&htype=15&port=1&name=Cozytouch_V'+str(version)+'&enabled=true'
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Réponse HTTP 200 OK
    if req.status_code==200 :
        data=json.loads(req.text)
        # Lecture de l'idx attribué
        idx=(data[u'idx'])
    else :
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
        idx=0
    print('    **** domoticz cozytouch hardware index : ',str(idx))
    return idx

def domoticz_add_virtual_device(idx,typ,nom,option='none'):
    ''' Fonction de création de device virtuel
    '''
    if option == 'none' :
        req_option = ''
    else :
        req_option=u'&sensoroptions=1;'+option
    idx = str(idx).decode("utf-8")
    typ = str(typ).decode("utf-8")

    myurl=url_domoticz+u'createvirtualsensor&idx='+idx+u'&sensorname='+nom+u'+&sensortype='+typ+req_option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    # Réponse HTTP 200 OK
    if req.status_code==200 :
        data=json.loads(req.text)
        # Lecture de l'idx attribué
        idx=(data[u'idx'])
    else :
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
        idx=0
    print('    **** domoticz virtual vensor index : '+str(idx))
    return idx

def domoticz_add_virtual_device_2(idx,typ,nom,unit=''):
    ''' Fonction de création de device virtuel
    '''
    idx = str(idx).decode("utf-8")
    typ = str(typ).decode("utf-8")

    myurl=url_domoticz+u'createdevice&idx='+idx+u'&sensorname='+nom+u'&sensormappedtype='+typ+u'&sensoroptions=1;'+unit
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    # Réponse HTTP 200 OK
    if req.status_code==200 :
        data=json.loads(req.text)
        # Lecture de l'idx attribué
        idx=(data[u'idx'])
    else :
        http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
        idx=0
    print('    **** domoticz virtual vensor index : '+str(idx))
    return idx


'''
**********************************************************
Fonctions génériques
**********************************************************
'''

def var_save(var, var_str):
    """Fonction de sauvegarde
    var: valeur à sauvegarder, var_str: nom objet en mémoire
    """
    d = shelve.open(cozytouch_save)
    if var_str in d :
        d[var_str] = var

    else :
        d[var_str] = 0 # init variable
        d[var_str] = var
        d.close()

def var_restore(var_str,format_str =False ):
    '''Fonction de restauration
    var_str: nom objet en mémoire
    '''
    d = shelve.open(cozytouch_save)
    if not (var_str) in d :
        if  format_str:
            value = 'init' # init variable
        else :
            value = 0 # init variable
    else :
        value = d[var_str]
    d.close()
    return value

def http_error(code_erreur, texte_erreur):
    ''' Evaluation des exceptions HTTP '''
    print("Erreur HTTP "+str(code_erreur)+" : "+texte_erreur)

'''
**********************************************************
Fonctions Cozytouch
**********************************************************
'''

def cozytouch_login(login,password):


    headers={
    'Content-Type':'application/x-www-form-urlencoded',
    'Authorization':'Basic czduc0RZZXdWbjVGbVV4UmlYN1pVSUM3ZFI4YTphSDEzOXZmbzA1ZGdqeDJkSFVSQkFTbmhCRW9h'
        }
    data={
        'grant_type':'password',
        'username':login,
        'password':password
        }

    url=url_atlantic+'/token'
    req = requests.post(url,data=data,headers=headers)

    atlantic_token=req.json()['access_token']

    headers={
    'Authorization':'Bearer '+atlantic_token+''
        }
    reqjwt=requests.get(url_atlantic+'/gacoma/gacomawcfservice/accounts/jwt',headers=headers)

    jwt=reqjwt.content.replace('"','')
    data={
        'jwt':jwt
        }
    jsession=requests.post(url_cozytouchlog+'/login',data=data)

    if debug:
        print(' POST-> '+url_cozytouchlog+"/login | userId=****&userPassword=**** : "+str(jsession.status_code))

    if jsession.status_code==200 : # Réponse HTTP 200 : OK
        print("Authentification serveur cozytouch OK")
        cookies =dict(JSESSIONID=(jsession.cookies['JSESSIONID'])) # Récupération cookie ID de session
        var_save(cookies,'cookies') #Sauvegarde cookie
        return True

    print("!!!! Echec authentification serveur cozytouch")
    http_error(req.status_code,req.reason)
    return False

def cozytouch_GET(json):
    ''' Fonction d'interrogation HTTP GET avec l'url par défaut
    json: nom de fonction JSON à transmettre au serveur
    '''
    headers = {
    'cache-control': "no-cache",
    'Host' : "ha110-1.overkiz.com",
    'Connection':"Keep-Alive",
    }
    myurl=url_cozytouch+json
    cookies=var_restore('cookies')
    req = requests.get(myurl,headers=headers,cookies=cookies)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    if req.status_code==200 : # Réponse HTTP 200 : OK
            data=req.json()
            return data

    http_error(req.status_code,req.reason) # Appel fonction sur erreur HTTP
    time.sleep(1) # Tempo entre requetes
    return None

def cozytouch_POST(url_device,name,parametre):
    # Fonction d'envoi requete POST vers serveur cozytouch

    # conversion entier ou flottant => unicode
    if isinstance (parametre,int) or isinstance (parametre,float):
        parametre = str(parametre).decode("utf-8")
    # si unicode, on teste si c'est un objet JSON '{}' dans ce cas on ne met pas de double quotes, sinon on applique par défaut
    elif isinstance (parametre,unicode) or isinstance (parametre,str)  and parametre.find('{') == -1 :
        parametre = u'"'+parametre+u'"'

    # Headers HTTP
    headers= {
    'content-type': "application/json",
    'cache-control': "no-cache"
    }
    myurl=url_cozytouch+u'../../enduserAPI/exec/apply'
    payload =u'{\"actions\": [{ \"deviceURL\": \"'+url_device+u'\" ,\n\"commands\": [{ \"name\": \"'+name+u'\",\n\"parameters\":['+parametre+u']}]}]}'
    cookies=var_restore('cookies')
    req = requests.post(myurl, data=payload, headers=headers,cookies=cookies)
    if debug:
        print(' POST-> '+myurl+" | "+payload+" : "+str(req.status_code))

    if req.status_code!=200 : # Réponse HTTP 200 : OK
        http_error(req.status_code,req.reason)
    return req.status_code

def test_exist_cozytouch_domoticz_hw_and_backup_store():

    print("**** Test existence / creation configuration cozytouch (hardware domoticz + fichier de sauvegarde) ****")
    if debug:
        print("Fichier de sauvegarde de la configuration : "+str(cozytouch_save))

    # Teste si le hardware cozytouch a déjà été créé dans domoticz ; sinon on le crée
    # Essaie de charger le fichier de sauvegarde
    try:
        shelve.open(cozytouch_save,'w') # Ouvrir la sauvegarde existante
    except:
        # Cas où le fichier de sauvegarde contenant l'idx du hardware cozytouch est inexistant:
        print("Fichier de sauvegarde de la configuration inexistant, creation hardware cozytouch dans domoticz et nouveau fichier de sauvegarde")
        d=shelve.open(cozytouch_save,'c')
        d.close()

        idx = domoticz_add_virtual_harware() # création d'un hardware de type virtual dans domoticz
        if idx == 0:
            print("!!!! Echec creation hardware cozytouch dans domoticz")
            return False

        var_save(idx,'save_idx') # création du fichier de sauvegarde de la configuration Cozytouch, et stockage du numéro du hardware cozytouch
        domoticz_write_log("Creation nouvelle configuration ...")
        print("Hardware cozytouch dans domoticz et nouveau fichier de sauvegarde de la configuration crees")

    # Cas où le fichier est existant et virtual hardware de domoticz inexistant/supprimé
    else :
        save_idx = var_restore('save_idx')
        print("idx hardware cozytouch dans le fichier de sauvegarde de la configuration : "+str(save_idx))

        # Test si le virtual hardware existe avec le même numéro dans domoticz
        myurl='http://'+domoticz_ip+':'+domoticz_port+'/json.htm?type=hardware'
        req=requests.get(myurl) # renvoie la liste du hardware domoticz
        if debug:
            print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

        if req.status_code==200 : #Réponse HTTP OK
            data=json.loads(req.text)
            # On boucle sur chaque hardware trouvé dans domoticz :
            y=0
            reset=False

            if 'result' in data:
                while True:
                    try :
                        data[u'result'][y]['idx']
                        a=data[u'result'][y]['idx']

                        if a==save_idx and data[u'result'][y][u'Name']=='Cozytouch_V'+str(version):
                            reset=False
                            print('idx hardware cozytouch dans domoticz : '+str(a))
                            break

                        elif a != save_idx:
                            y+=1
                            continue

                        else :
                            reset=True
                            break
                    except:
                        reset=True
                        break
            else :
                reset=True

            if reset :
                print("**** Reset configuration cozytouch ****")
                domoticz_write_log("Cozytouch : creation nouvelle configuration ...")

                # on supprime le fichier de sauvegarde
                print("Suppression fichier de sauvegarde...")
                if os.path.isfile(cozytouch_save):
                    os.remove(cozytouch_save)
                if os.path.isfile(cozytouch_save+".dat"):
                    os.remove(cozytouch_save+".dat")
                if os.path.isfile(cozytouch_save+".bak"):
                    os.remove(cozytouch_save+".bak")
                if os.path.isfile(cozytouch_save+".dir"):
                    os.remove(cozytouch_save+".dir")

                # et création d'un hardware de type virtual dans domoticz
                print("Ajout materiel Cozytouch et fichier Cozytouch_save...")
                idx = domoticz_add_virtual_harware()
                if idx == 0:
                    print("!!!! Echec creation hardware cozytouch dans domoticz")
                    return False

                var_save(idx,'save_idx') # création du fichier de sauvegarde de la configuration Cozytouch, et stockage du numéro du hardware cozytouch
        else:
            print("!!!! Echec recuperation liste hardware dans domoticz")
            return False

    print("**** Fin fonction test ****")
    return True


def read_label_from_cozytouch(data,x,oid='none'):

    # Lecture du nom lorsqu'il est placé directement dans l'architecture du device
    if oid=='none' :
        label=data[u'setup'][u'devices'][x][u'label']

    # Lecture du nom du device lorsqu'il est placé sous l'architecture 'rootplace'
    # On cherche le numéro 'oid' correspondant au device pour récupérer le nom
    else :
        # Init variable
        y=0
        z=(data[u'setup'][u'rootPlace'][u'subPlaces'])
        while True:
            try :
                oid_subplace=(z[y][u'oid'])
                if oid_subplace == oid:
                    label=(z[y][u'label'])
                    break
                else:
                    y+=1
                    continue
            except:
                label=u'noname'
                break
    return label.strip()

def decouverte_devices():

    ''' Fonction de découverte des devices Cozytouch
    Scanne les devices présents dans l'api cozytouch et gère les ajouts à Domoticz
    '''
    print("**** Decouverte devices ****")

    # Renvoi toutes les données du cozytouch
    data = cozytouch_GET('getSetup')

    if debug==2:
	    f1=open('./dump_cozytouch.txt', 'w+')
	    f1.write((json.dumps(data, indent=4, separators=(',', ': '))))
	    f1.close()


    # Lecture données Gateway Cozytouch (pour info)
    select=(data[u'setup'][u'gateways'][0])
    if select[u'alive']:
        cozytouch_gateway_etat="on"
    else:
        cozytouch_gateway_etat="off"
    if debug:
        print("\nGateway Cozytouch : etat "+cozytouch_gateway_etat+" / connexion : "+select[u'connectivity'][u'status']+" / version : "+str(select[u'connectivity'][u'protocolVersion']))

    # Restauration de la liste des devices
    save_devices = var_restore('save_devices')
    # Restauration de l'idx hardware cozytouch dans domoticz
    save_idx = var_restore('save_idx')

    '''
    Cas de la liste vide, au premier démarrage du script par ex.
    On passe en revue les devices de l'API Cozytouch et on l'ajoute à une liste
    si sa classe est connu dans le dictionnaire Cozytouch
    '''
    if not save_devices : # si la liste est vide on passe à la création des devices
        print("**** Demarrage procedure d'ajout devices Cozytouch **** ")
        liste=[]    # on crée une liste vide
        domoticz_write_log(u'Cozytouch : Recherche des devices connectes ... ')
        # Initialisation variables
        x = 0
        p = 0
        oid = 0

        # On boucle sur chaque device trouvé :
        for a in data[u'setup'][u'devices']:
            url = a[u'deviceURL']
            name = a[u'controllableName']
            oid = a[u'placeOID']

            if name == dict_cozytouch_devtypes.get(u'radiateur'): # on vérifie si le nom du device est connu
               label = read_label_from_cozytouch(data,x,oid)
               liste= ajout_radiateur(save_idx,liste,url,x,label)   # ajout du device à la liste
               p+=1 # incrément position dans dictionnaire des devices

            elif name == dict_cozytouch_devtypes.get(u'chauffe eau'):
                liste = ajout_chauffe_eau (save_idx,liste,url,x,(data[u'setup'][u'rootPlace'][u'label'])) # label rootplace
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'module fil pilote'):
                liste= ajout_module_fil_pilote (save_idx,liste,url,x,read_label_from_cozytouch(data,x,oid))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'PAC main control'):
                liste= ajout_PAC_main_control (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'PAC zone control'):
                liste= ajout_PAC_zone_control (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'DHWP_THERM_V3_IO') or name == dict_cozytouch_devtypes.get(u'DHWP_THERM_IO') or name == dict_cozytouch_devtypes.get(u'DHWP_THERM_V2_MURAL_IO') :
                liste= Add_DHWP_THERM (save_idx,liste,url,x,(data[u'setup'][u'rootPlace'][u'label']),name) # label sur rootplace
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'bridge cozytouch'):
                label = u'localisation inconnue'
                liste= ajout_bridge_cozytouch (save_idx,liste,url,x,label)
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'PAC_HeatPump'):
                liste= ajout_PAC_HeatPump (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'PAC OutsideTemp'):
                liste= ajout_PAC_Outside_Temp (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'PAC InsideTemp'):
                liste= ajout_PAC_Inside_Temp (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'PAC Electrical Energy Consumption'):
                liste= ajout_PAC_Electrical_Energy (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'PAC zone component'):
                liste= ajout_PAC_zone_component (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1
				
            elif name == dict_cozytouch_devtypes.get(u'DHWP_MBL'):
                liste= add_DHWP_MBL (save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1

            elif name == dict_cozytouch_devtypes.get(u'DHWP_MBL_CEEC'):
                liste= add_DHWP_MBL_CEEC(save_idx,liste,url,x,read_label_from_cozytouch(data,x))
                p+=1
				
            else :
                domoticz_write_log(u'Cozytouch : Device avec classe '+name+u' inconnu')


            x+=1 # incrément device dans data json cozytouch

        # Fin de la boucle :
        # Sauvegarde des devices ajoutés
        var_save(liste,'save_devices')

    '''
    Cas de liste non vide
    On passe en revue les devices l'API Cozytouch
    si sa classe est connue dans le dictionnaire Cozytouch on met à jour les données
    '''
    if save_devices != 0 : # si la liste contient des devices
        print("\n**** Demarrage mise a jour devices ****")
        # Initialisation variables
        liste_inconnu = []
        x = 0
        p = 0
        # On boucle sur chaque device trouvé :
        for a in data[u'setup'][u'devices']:
            url = a[u'deviceURL']
            name = a[u'controllableName']

            # On boucle sur les éléments du dictionnaire de devices
            for element in save_devices :
                if element.has_key(u'url') : # si la clé url est présente dans le dictionnaire
                    if element.get(u'url') == url :  # si l'url du device est stocké dans le dictionnaire
                        maj_device(data,name,p,x) # mise à jour du device
                        p+=1 # incrément position dans le dictionnaire

                        for inconnu in liste_inconnu :
                            if inconnu == url :
                                liste_inconnu.remove(url) # on retire l'url inconnu à la liste
                        break

                    else : # sinon on reboucle
                        liste_inconnu.append(url)

                else : # sinon on reboucle
                    continue

            x+=1 # incrément position du device dans les datas json cozytouch

'''
**********************************************************
Fonctions d'ajouts des devices cozytouch dans Domoticz
suivant la classe
**********************************************************
'''

def ajout_radiateur(idx,liste,url,x,label):
    ''' Fonction ajout radiateur
    '''
    # TODO : traiter comme erreur les domoticz_add_virtual_device renvoyant 0

    # création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = u'Rad. '+label

    # création du dictionnaire de définition du device
    radiateur = {}
    radiateur[u'url'] = url
    radiateur[u'x']= x
    radiateur[u'nom']= nom

    # Création switch selecteur mode de fonctionnement (level_0=off/level_10=Manuel/level_20=Auto(prog)) :
    nom_switch = u'Mode '+nom
    radiateur[u'idx_switch_mode']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch(Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8TWFudWVsfEF1dG8gKHByb2cpO0xldmVsQWN0aW9uczp8fDtTZWxlY3RvclN0eWxlOjA7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true'
    myurl=u'http://'+domoticz_ip+u':'+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+radiateur[u'idx_switch_mode']+u'&name='+nom_switch+u'+&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Création switch selecteur (level_10=frostprotection/level_20=eco/level_30=confort-2/level_40=confort-1/level_50=confort) :
    nom_switch = u'Ordre '+nom
    radiateur[u'idx_switch_level']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch(Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8SG9ycyBnZWx8RWNvfENvbmZvcnQgLTJ8Q29uZm9ydCAtMXxDb25mb3J0O0xldmVsQWN0aW9uczp8fHx8fDtTZWxlY3RvclN0eWxlOjE7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true'
    myurl=u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+radiateur[u'idx_switch_level']+u'&name='+nom_switch+u'+&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))


    # Consigne de dérogation valable en mode auto, applique une consigne de dérogation commande :"setDerogatedTargetTemperature" + température souhaité
    # Fonctionnement de la dérogation : En mode auto, si on applique uen consigne > à la consigne en cours (eco ou confort), on applique la dérogation (retour d'état pour savoir si on est dérogation? pas trouvé encore)
    # POur annuler la dérogation il faut appliquer la consigne qui doit etre en cours soit eco ou confort suivant le mode du radiateur,
    #Attention le radiateur n'accepte pas une consigne de dérogation inférieure à la consigne qui doit etre appliquée (eco ou confort)

    # Création Mesure température :
    nom_mesure = u'T°C '+nom
    radiateur[u'idx_mesure_temp']= domoticz_add_virtual_device(idx,80,nom_mesure)

    # Création Consigne température Confort :
    nom_cons_conf = u'Cons. confort '+nom
    radiateur[u'idx_cons_temp_confort']= domoticz_add_virtual_device(idx,8,nom_cons_conf )

    # Création Consigne température Eco :
    nom_cons_eco= u'Cons. éco '+nom
    radiateur[u'idx_cons_temp_eco']= domoticz_add_virtual_device(idx,8,nom_cons_eco)

    # Création Compteur d'énergie :
    nom_compteur= u'Conso '+nom
    radiateur[u'idx_compteur']= domoticz_add_virtual_device(idx,113,nom_compteur)

    # Log Domoticz :
    domoticz_write_log(u'Cozytouch : creation '+nom+u' ,url: '+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(radiateur)

    print(u'Ajout: '+nom)
    return liste

def ajout_module_fil_pilote(idx,liste,url,x,label):
    ''' Fonction ajout module fil pilote
    '''

    # création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = 'Module fil pilote '+str(label)

    # création du dictionnaire de définition du device
    module_fil_pilote = {}
    module_fil_pilote['url'] = url
    module_fil_pilote['x']= x
    module_fil_pilote['nom']= nom

    # Création switch selecteur (level_0=off/level_10=frostprotection/level_20=eco/level_30=confort-2/level_40=confort-1/level_50=confort) :
    nom_switch = u'Mode '+nom
    radiateur[u'idx_switch']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch(Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8SG9ycyBnZWx8RWNvfENvbmZvcnQgLTJ8Q29uZm9ydCAtMXxDb25mb3J0O0xldmVsQWN0aW9uczp8fHx8fDtTZWxlY3RvclN0eWxlOjE7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true'
    myurl=u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+radiateur[u'idx_switch']+u'&name='+nom_switch+u'+&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(module_fil_pilote)

    print("Ajout: "+nom)
    return liste

def ajout_chauffe_eau(idx,liste,url,x,label):
    ''' Fonction ajout chauffe eau
    '''
    # création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = 'Chauffe eau '+str(label)
    nom.encode('utf-8')

    # création du dictionnaire de définition du device
    chauffe_eau= {}
    chauffe_eau['url'] = url
    chauffe_eau['x']= x
    chauffe_eau['nom']= nom

    # Switch selecteur auto/manu/manu+eco:
    nom_switch = 'Mode '+nom
    chauffe_eau['idx_switch_auto_manu']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch (Modification du nom des levels et de l'icone)
    option = 'TGV2ZWxOYW1lcyUzQUF1dG8lN0NNYW51JTdDTWFudStFY28lM0JMZXZlbEFjdGlvbnMlM0ElN0MlN0MlN0MlM0JTZWxlY3RvclN0eWxlJTNBMCUzQkxldmVsT2ZmSGlkZGVuJTNBZmFsc2UlM0I='
    myurl='http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(chauffe_eau['idx_switch_auto_manu'])+'&name='+nom_switch+'&description=&strparam1=&strparam2=&protected=false&switchtype=18&customimage=15&used=true&addjvalue=0&addjvalue2=0&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Switch on/off
    nom_switch_on_off = 'Etat '+nom
    chauffe_eau['idx_on_off']= domoticz_add_virtual_device(idx,6,nom_switch_on_off)
    myurl='http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(chauffe_eau['idx_on_off'])+'&name='+nom_switch_on_off+'&description=&strparam1=&strparam2=&protected=false&switchtype=0&customimage=15&used=true&addjvalue=0&addjvalue2=0&options='
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Mesure température eau:
    nom_mesure = 'Temperature eau '+nom
    chauffe_eau['idx_mesure_temp']= domoticz_add_virtual_device(idx,80,nom_mesure)

    # Compteur d'eau :
    nom_compteur= 'Eau restante '+nom
    chauffe_eau['idx_conso_eau']= domoticz_add_virtual_device(idx,1004,nom_compteur,option='litres')

    # Personnalisation du switch (Modification de l'icone)
    myurl='http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(chauffe_eau['idx_conso_eau'])+'&name='+nom_compteur+'&description=&switchtype=2&addjvalue=0&used=true&options='
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Compteur temps de fonctionnement pompe à chaleur :
    nom_compteur_pompe = 'Pompe a chaleur '+nom
    chauffe_eau['idx_compteur_pompe']= domoticz_add_virtual_device(idx,113,nom_mesure)
    # Personnalisation du switch (Modification du nom des levels et de l'icone)
    option = 'VmFsdWVRdWFudGl0eSUzQUglM0JWYWx1ZVVuaXRzJTNBSGV1cmVzJTNC'
    myurl='http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(chauffe_eau['idx_compteur_pompe'])+'&name='+nom_compteur_pompe+'&switchtype=3&addjvalue=0&used=true&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Compteur d'énergie :
    nom_compteur= 'Energie '+nom
    chauffe_eau['idx_compteur']= domoticz_add_virtual_device(idx,18,nom_compteur)

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(chauffe_eau)

    print("Ajout: "+nom)
    return liste


def ajout_PAC_main_control  (idx,liste,url,x,label):
    ''' Fonction ajout PAC (controle général)
    '''
    # création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = u'PAC '+label

    # création du dictionnaire de définition du device
    PAC_main_control = {}
    PAC_main_control [u'url'] = url
    PAC_main_control [u'x']= x
    PAC_main_control [u'nom']= nom

    # Switch selecteur stop/heating/cooling/drying/auto
    nom_switch = u'Mode PAC '+label
    PAC_main_control [u'idx_switch_mode']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch (Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8Q2hhdWZmYWdlfFJlZnJvaWRpc3NlbWVudHxEw6lzaHVtaWRpZmljYXRldXJ8QXV0bztMZXZlbEFjdGlvbnM6fHx8fDtTZWxlY3RvclN0eWxlOjE7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true'
    myurl=u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?type=setused&idx='+(PAC_main_control[u'idx_switch_mode'])+u'&name='+nom_switch+u'&description=&strparam1=&strparam2=&protected=false&switchtype=18&customimage=7&used=true&addjvalue=0&addjvalue2=0&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(PAC_main_control)

    print(u"Ajout: "+nom)
    return liste


def ajout_PAC_zone_control  (idx,liste,url,x,label):
    ''' Fonction ajout PAC (controle zone)
    '''
    # Création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = u'PAC '+label

    # Création du dictionnaire de définition du device
    PAC_zone_control = {}
    PAC_zone_control [u'url'] = url
    PAC_zone_control [u'x']= x
    PAC_zone_control [u'nom']= nom

    # Création Mesure température :
    nom_mesure = u'T°C '+nom
    PAC_zone_control [u'idx_mesure_temp']= domoticz_add_virtual_device(idx,80,nom_mesure)

    # Création Mode de fonctionnement PAC : Switch selecteur off/manu/programmation
    nom_switch = u'Mode PAC '+label
    nom_switch = nom_switch.encode('utf8')
    PAC_zone_control [u'idx_switch_mode']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch (Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8TWFudWVsfEF1dG8gKFByb2cpO0xldmVsQWN0aW9uczp8fDtTZWxlY3RvclN0eWxlOjA7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D'
    myurl=u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?type=setused&idx='+(PAC_zone_control[u'idx_switch_mode'])+u'&name='+nom_switch+u'&description=&strparam1=&strparam2=&protected=false&switchtype=18&customimage=7&used=true&addjvalue=0&addjvalue2=0&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Consigne température Confort en mode chauffage : (core:ComfortHeatingTargetTemperatureState)
    nom_cons_conf_chauffage = u'Confort chauff. '+nom
    PAC_zone_control [u'idx_cons_temp_confort_chauffage'] = domoticz_add_virtual_device(idx,8,nom_cons_conf_chauffage)

    # Consigne température Confort mode climatisation :
    nom_cons_conf_clim = u'Confort rafraich. '+nom
    PAC_zone_control [u'idx_cons_temp_confort_clim'] = domoticz_add_virtual_device(idx,8,nom_cons_conf_clim)

    # Consigne température Eco mode chauffage :
    nom_cons_eco_chauffage = u'Eco chauff. '+nom
    PAC_zone_control [u'idx_cons_temp_eco_chauffage']= domoticz_add_virtual_device(idx,8,nom_cons_eco_chauffage)

    # Consigne température Eco mode clim :
    nom_cons_eco_clim = u'Eco rafraich. '+nom
    PAC_zone_control [u'idx_cons_temp_eco_clim']= domoticz_add_virtual_device(idx,8,nom_cons_eco_clim)

    # Consigne température mode manuel :
    nom_cons_manu = u'Manuel '+nom
    PAC_zone_control [u'idx_cons_temp_manu']= domoticz_add_virtual_device(idx,8,nom_cons_manu)

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(PAC_zone_control)

    print(u"Ajout: "+nom)
    return liste

def Add_DHWP_THERM (idx,liste,url,x,label,name):
    #Fonction ajout DHWP_THERM_IO

    ######
    # Widgets added for Common Class :

    # création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = u'DHWP '+label
    nom.encode('utf-8')
    # création du dictionnaire de définition du device
    DHWP_THERM= {}
    DHWP_THERM[u'url'] = url
    DHWP_THERM[u'x']= x
    DHWP_THERM[u'nom']= nom

     # Switch on/off (OperatingModeCapabilitiesState)
    nom_switch_on_off = u'Etat chauffe '+nom
    DHWP_THERM[u'idx_on_off']= domoticz_add_virtual_device(idx,6,nom_switch_on_off)
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(DHWP_THERM['idx_on_off'])+'&name='+nom_switch_on_off+'&description=&strparam1=&strparam2=&protected=false&switchtype=0&customimage=15&used=true&addjvalue=0&addjvalue2=0&options=')

    # Compteur temps de fonctionnement pompe à chaleur (HeatPumpOperatingTimeState)
    nom_compteur_pompe = u'Compteur PAC '+nom
    DHWP_THERM['idx_compteur_pompe']= domoticz_add_virtual_device(idx,113,nom_compteur_pompe)
    # Personnalisation du switch (Modification du nom des levels et de l'icone
    option = 'VmFsdWVRdWFudGl0eTpIZXVyZXM7VmFsdWVVbml0czpIOw=='
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(DHWP_THERM['idx_compteur_pompe'])+'&name='+nom_compteur_pompe+'&description=&switchtype=3&addjvalue=0&used=true&options='+option)

    # Compteur d'énergie (ElectricEnergyConsumptionState)
    nom_compteur= u'Energie '+nom
    DHWP_THERM[u'idx_compteur_energie']= domoticz_add_virtual_device(idx,113,nom_compteur)

    # Consigne température  :
    nom_cons_conf = u'Consigne Temp '+nom
    DHWP_THERM[u'idx_cons_temp']= domoticz_add_virtual_device(idx,8,nom_cons_conf )
    # Création Compteur d'énergie :
    nom_compteur= u'Conso '+nom
    DHWP_THERM[u'idx_compteur']= domoticz_add_virtual_device(idx,113,nom_compteur)
    # Switch selecteur :
    nom_switch = u'Mode '+nom
    DHWP_THERM[u'idx_switch_mode']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch (Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8TWFudWFsfE1hbnVhbCtlY298QXV0b3xCb29zdDtMZXZlbEFjdGlvbnM6fHx8fDtTZWxlY3RvclN0eWxlOjA7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D'
    send=requests.get(u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+(DHWP_THERM[u'idx_switch_mode'])+'&name='+nom_switch+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    # Switch selecteur boost duration:
    nom_switch = u'Duree boost (jours) '+nom
    DHWP_THERM[u'idx_boost_duration']= domoticz_add_virtual_device(idx,1002,nom_switch)
    # Personnalisation du switch (Modification du nom des levels et de l'icone
    option = u'TGV2ZWxOYW1lczowfDF8MnwzfDR8NXw2fDc7TGV2ZWxBY3Rpb25zOnx8fHx8fHw7U2VsZWN0b3JTdHlsZTowO0xldmVsT2ZmSGlkZGVuOmZhbHNl'
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+(DHWP_THERM['idx_boost_duration'])+'&name='+nom_switch+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    # Switch selecteur durée absence :
    nom_switch = u'Duree absence (jours) '+nom
    DHWP_THERM[u'idx_away_duration']= domoticz_add_virtual_device(idx,1002,nom_switch)
    # Personnalisation du switch (Modification du nom des levels et de l'icone
    option = u'TGV2ZWxOYW1lczowfDF8MnwzfDR8NXw2fDc7TGV2ZWxBY3Rpb25zOnx8fHx8fHw7U2VsZWN0b3JTdHlsZTowO0xldmVsT2ZmSGlkZGVuOmZhbHNl'
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+(DHWP_THERM['idx_away_duration'])+'&name='+nom_switch+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    ######
    # Widgets added only for SubClass  "io:AtlanticDomesticHotWaterProductionV2_MURAL_IOComponent"
    if name == dict_cozytouch_devtypes.get(u'DHWP_THERM_V2_MURAL_IO') :

        # Add Temperature of water (io:MiddleWaterTemperatureState)
        widget_name = u'Temp '+nom
        DHWP_THERM[u'idx_temp_measurement']= domoticz_add_virtual_device(idx,80,widget_name)

        # Add Heat Pump Energy Counter (io:PowerHeatPumpState)
        widget_name = u'Energy HeatPump '+nom
        DHWP_THERM[u'idx_energy_counter_heatpump']= domoticz_add_virtual_device(idx,113,widget_name)

        # Add Heat Electrical Energy Counter (io:PowerHeatElectricalState)
        widget_name = u'Energy Elec '+nom
        DHWP_THERM[u'idx_energy_counter_heatelec']= domoticz_add_virtual_device(idx,113,widget_name)

        # Add Water volume estimation (core:V40WaterVolumeEstimationState)
        # V40 is measured in litres (L) and shows the amount of warm (mixed) water with a temperature of 40℃, which can be drained from a switched off electric water heater
        widget_name = u'Estimated volume at 40 deg '+nom
        DHWP_THERM[u'idx_water_estimation']= domoticz_add_virtual_device(idx,113,widget_name)
        # Personnalisation du compteur
        send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?addjvalue=0&addjvalue2=0&customimage=2&description=&idx='+(DHWP_THERM['idx_water_estimation'])+'&name='+widget_name+'&switchtype=2&addjvalue=0&addjvalue2=0&used=true&options=')

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : création "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(DHWP_THERM)

    print ("Ajout: "+nom)
    return liste

def ajout_PAC_HeatPump  (idx,liste,url,x,label):
    ''' Fonction ajout PAC HeatPump (controle général)
    '''
    # création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = u'PAC '+label

    # création du dictionnaire de définition du device
    PAC_HeatPump = {}
    PAC_HeatPump [u'url'] = url
    PAC_HeatPump[u'x']= x
    PAC_HeatPump[u'nom']= nom

    # Switch selecteur stop/heating/cooling/drying/auto
    nom_switch = u'Mode PAC '+label
    PAC_HeatPump [u'idx_switch_mode']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch (Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8Q2hhdWZmYWdlfFJlZnJvaWRpc3NlbWVudHxEw6lzaHVtaWRpZmljYXRldXJ8QXV0bztMZXZlbEFjdGlvbnM6fHx8fDtTZWxlY3RvclN0eWxlOjE7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true'
    myurl=u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?type=setused&idx='+(PAC_HeatPump[u'idx_switch_mode'])+u'&name='+nom_switch+u'&description=&strparam1=&strparam2=&protected=false&switchtype=18&customimage=7&used=true&addjvalue=0&addjvalue2=0&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))
    
    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(PAC_HeatPump)

    print(u"Ajout: "+nom)
    return liste

def ajout_PAC_Outside_Temp (idx,liste,url,x,label):
    ''' Fonction ajout T°C Extérieure PAC
    '''
    # création du nom 
    nom = u'Outside T°C'
	
    # création du dictionnaire de définition du device
    PAC_Outside_Temp = {}
    PAC_Outside_Temp [u'url'] = url
    PAC_Outside_Temp [u'x']= x
    PAC_Outside_Temp [u'nom']= nom

    # Création Mesure température Extérieur :
    PAC_Outside_Temp [u'idx_mesure_temp']= domoticz_add_virtual_device(idx,80,nom)

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(PAC_Outside_Temp)

    #print(u"Ajout: "+nom.encode('utf-8'))
    return liste

def ajout_PAC_Inside_Temp (idx,liste,url,x,label):
    ''' Fonction ajout T°C Intérieure PAC
    '''
    # création du nom 
    nom = u'Inside T°C'
    
    # création du dictionnaire de définition du device
    PAC_Inside_Temp = {}
    PAC_Inside_Temp [u'url'] = url
    PAC_Inside_Temp [u'x']= x
    PAC_Inside_Temp [u'nom']= nom

    # Création Mesure température Extérieur :
    PAC_Inside_Temp [u'idx_mesure_temp']= domoticz_add_virtual_device(idx,80,nom)

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(PAC_Inside_Temp)
    return liste

def ajout_PAC_Electrical_Energy (idx,liste,url,x,label):
    ''' Fonction ajout Compteurs energies 1 + 2
    '''
    # création du nom 
    nom = u'Compteurs Energie'
    
    # création du dictionnaire de définition du device
    PAC_Electrical_Energy = {}
    PAC_Electrical_Energy [u'url'] = url
    PAC_Electrical_Energy [u'x']= x
    PAC_Electrical_Energy [u'nom']= nom

    # Création Compteur d'énergie 1 :
    nom_compteur= u'Energy 1'
    PAC_Electrical_Energy [u'idx_compteur_1']= domoticz_add_virtual_device(idx,113,nom_compteur)

    # Création Compteur d'énergie 2 :
    nom_compteur= u'Energy 2'
    PAC_Electrical_Energy [u'idx_compteur_2']= domoticz_add_virtual_device(idx,113,nom_compteur)
    
    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(PAC_Electrical_Energy)
    print(u"Ajout: "+nom)
    return liste

def ajout_PAC_zone_component (idx,liste,url,x,label):
    ''' Fonction ajout PAC (controle zone)
    '''
    # Création du nom suivant la position JSON du device dans l'API Cozytouch
    nom = u'PAC '+label

    # Création du dictionnaire de définition du device
    PAC_zone_component = {}
    PAC_zone_component  [u'url'] = url
    PAC_zone_component  [u'x']= x
    PAC_zone_component  [u'nom']= nom

    # Création Mode de fonctionnement PAC : Switch selecteur off/manu/programmation
    nom_switch = u'Mode PAC '+label
    nom_switch = nom_switch.encode('utf8')
    PAC_zone_component [u'idx_switch_mode']= domoticz_add_virtual_device(idx,1002,nom)
    # Personnalisation du switch (Modification du nom des levels et de l'icone)
    option = u'TGV2ZWxOYW1lczpPZmZ8TWFudWVsfEF1dG8gKFByb2cpO0xldmVsQWN0aW9uczp8fDtTZWxlY3RvclN0eWxlOjA7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D'
    myurl=u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?type=setused&idx='+(PAC_zone_component[u'idx_switch_mode'])+u'&name='+nom_switch+u'&description=&strparam1=&strparam2=&protected=false&switchtype=18&customimage=7&used=true&addjvalue=0&addjvalue2=0&options='+option
    req=requests.get(myurl)
    if debug:
        print(u'  '.join((u'GET-> ',myurl,' : ',str(req.status_code))).encode('utf-8'))

    # Consigne température Confort en mode chauffage : (core:ComfortHeatingTargetTemperatureState)
    nom_cons_conf_chauffage = u'Confort chauff. '+nom
    PAC_zone_component [u'idx_cons_temp_confort_chauffage'] = domoticz_add_virtual_device(idx,8,nom_cons_conf_chauffage)

    # Consigne température Eco mode chauffage :
    nom_cons_eco_chauffage = u'Eco chauff. '+nom
    PAC_zone_component [u'idx_cons_temp_eco_chauffage']= domoticz_add_virtual_device(idx,8,nom_cons_eco_chauffage)

     # Consigne température mode manuel :
    nom_cons_manu = u'Manuel '+nom
    PAC_zone_component [u'idx_cons_temp_manu']= domoticz_add_virtual_device(idx,8,nom_cons_manu)

    # Switch selecteur durée absence :
    nom_switch = u'Duree absence (jours) '+nom
    PAC_zone_component[u'idx_away_duration']= domoticz_add_virtual_device(idx,1002,nom_switch)
    # Personnalisation du switch (Modification du nom des levels et de l'icone
    option = u'TGV2ZWxOYW1lczowfDF8MnwzfDR8NXw2fDc7TGV2ZWxBY3Rpb25zOnx8fHx8fHw7U2VsZWN0b3JTdHlsZTowO0xldmVsT2ZmSGlkZGVuOmZhbHNl'
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+(PAC_zone_component['idx_away_duration'])+'&name='+nom_switch+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    # Switch selecteur durée dérogation :
    nom_switch = u'Duree derog. (H) '+nom
    PAC_zone_component[u'idx_derog_duration']= domoticz_add_virtual_device(idx,1002,nom_switch)
    # Personnalisation du switch (Modification du nom des levels et de l'icone
    option = u'TGV2ZWxOYW1lczowfDF8MnwzfDR8NXw2fDd8ODtMZXZlbEFjdGlvbnM6fHx8fHx8fHw7U2VsZWN0b3JTdHlsZTowO0xldmVsT2ZmSGlkZGVuOmZhbHNl'
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+(PAC_zone_component['idx_derog_duration'])+'&name='+nom_switch+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(PAC_zone_component)

    print(u"Ajout: "+nom)
    return liste

def add_DHWP_MBL (idx,liste,url,x,label):
    ''' Add Water Heater DHWP_MBL
    '''
    # Création du nom suivant la position JSON du device dans l'API Cozytouch
    Device_name= u'Water Heater '+label
	
    # Création du dictionnaire de définition du device
    DHWP_MBL = {}
    DHWP_MBL [u'url'] = url
    DHWP_MBL [u'x']= x
    DHWP_MBL [u'nom']= Device_name

    # Add : Heating state (Data : modbuslink:PowerHeatElectricalState)
    Widget_name = u'Heating state '+Device_name
    DHWP_MBL [u'idx_HeatingStatusState']= domoticz_add_virtual_device(idx,6,Widget_name)
    # Setting widget
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(DHWP_MBL['idx_HeatingStatusState'])+'&name='+Widget_name+'&description=&strparam1=&strparam2=&protected=false&switchtype=0&customimage=15&used=true&addjvalue=0&addjvalue2=0&options=')

    # Add : Temperature Setpoint (Data : core:WaterTargetTemperatureState / SetTargetTemperature)
    Widget_name = u'Setpoint '+Device_name
    DHWP_MBL[u'idx_WaterTargetTemperature']= domoticz_add_virtual_device(idx,8,Widget_name)
    
    # Add : Mode Selector (auto/manual) (Data : modbuslink:DHWModeState / setDHWMode)
    Widget_name = u'Mode '+Device_name
    DHWP_MBL[u'idx_Mode']= domoticz_add_virtual_device(idx,1002,Widget_name)
    # Setting widget
    option = u'TGV2ZWxOYW1lczpBdXRvfE1hbnVhbDtMZXZlbEFjdGlvbnM6fDtTZWxlY3RvclN0eWxlOjA7TGV2ZWxPZmZIaWRkZW46ZmFsc2U%3D'
    send=requests.get(u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+(DHWP_MBL[u'idx_Mode'])+'&name='+Widget_name+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    # Add : Temperature of water (modbuslink:MiddleWaterTemperatureState)
    Widget_name = u'Middle Temp '+Device_name
    DHWP_MBL [u'idx_MiddleWaterTemperatureState']= domoticz_add_virtual_device(idx,80,Widget_name)

    # Add : Temperature of water (core:BottomTankWaterTemperatureState)
    Widget_name = u'Bottom Temp '+Device_name
    DHWP_MBL [u'idx_BottomTankWaterTemperatureState']= domoticz_add_virtual_device(idx,80,Widget_name)

    # Add : Temperature of water (core:ControlWaterTargetTemperatureState)
    Widget_name = u'Control Temp '+Device_name
    DHWP_MBL [u'idx_ControlWaterTargetTemperatureState']= domoticz_add_virtual_device(idx,80,Widget_name)

    # Add : Water volume estimation (core:V40WaterVolumeEstimationState)
    # V40 is measured in litres (L) and shows the amount of warm (mixed) water with a temperature of 40℃, which can be drained from a switched off electric water heater
    #Widget_name = u'Estimated volume @ 40 Deg '+Device_name
    #DHWP_MBL[u'idx_V40WaterVolumeEstimationState']= domoticz_add_virtual_device(idx,113,Widget_name)
    # Setting widget
    #send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(DHWP_MBL['idx_water_estimation'])+'&name='+Widget_name+'&description=&switchtype=0&customimage=11&devoptions=1%3BL&used=true')

    # Add : Remaining Hot water (core:RemainingHotWaterState)
    Widget_name = u'Remaining Hot Water '+Device_name
    DHWP_MBL [u'idx_RemainingHotWaterState']= domoticz_add_virtual_device_2 (idx,u'0xF31F',Widget_name,u'L')
    # Setting widget    
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(DHWP_MBL[u'idx_RemainingHotWaterState'])+'&name='+Widget_name+'&customimage=11&devoptions=&used=true')

    # Add : Remaining Hot water in percent (#)
    Widget_name = u'Remaining Hot Water '+Device_name
    DHWP_MBL [u'idx_RemainingHotWaterState_in_percent']= domoticz_add_virtual_device_2 (idx,u'0xF306',Widget_name)
    # Setting widget
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(DHWP_MBL[u'idx_RemainingHotWaterState_in_percent'])+'&name='+Widget_name+'&customimage=11&devoptions=&used=true')
    
    # Add : Number of showers remaining (core:NumberOfShowerRemainingState)
    Widget_name = u'Nbr of showers remaining '+Device_name
    DHWP_MBL[u'idx_NumberOfShowerRemainingState']= domoticz_add_virtual_device_2 (idx,u'0xF31F',Widget_name,u'L')
    # Setting widget
    send=requests.get('http://'+domoticz_ip+":"+domoticz_port+'/json.htm?type=setused&idx='+(DHWP_MBL['idx_NumberOfShowerRemainingState'])+'&name='+Widget_name+'&description=&switchtype=0&customimage=11&devoptions=1%3BShowers&used=true')

    # Add : Boost selector (Data : modbuslink:DHWBoostModeState / setBoostMode)
    Widget_name = u'Boost mode '+Device_name
    DHWP_MBL[u'idx_DHWBoostModeState']= domoticz_add_virtual_device_2(idx,u'0xF43E',Widget_name)
    # Setting widget
    option = u'TGV2ZWxOYW1lczpPZmZ8T247TGV2ZWxBY3Rpb25zOnw7U2VsZWN0b3JTdHlsZTowO0xldmVsT2ZmSGlkZGVuOmZhbHNl'
    send=requests.get(u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=15&description=&idx='+(DHWP_MBL[u'idx_DHWBoostModeState'])+'&name='+Widget_name+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    # Add : Absence selector (Data : modbuslink:DHWAbsenceModeState / setAbsenceMode)
    Widget_name = u'Absence mode '+Device_name
    DHWP_MBL[u'idx_DHWAbsenceModeState']= domoticz_add_virtual_device_2(idx,u'0xF43E',Widget_name)
    # Setting widget
    option = u'TGV2ZWxOYW1lczpPZmZ8T247TGV2ZWxBY3Rpb25zOnw7U2VsZWN0b3JTdHlsZTowO0xldmVsT2ZmSGlkZGVuOmZhbHNl'
    send=requests.get(u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=0&description=&idx='+(DHWP_MBL[u'idx_DHWAbsenceModeState'])+'&name='+Widget_name+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')

    # Add : Expected Hot water Quantity requested only in manual mode, in % (Data : core:ExpectedNumberOfShowerState / setExpectedNumberOfShower)
    Widget_name = u'Expected Qty'+Device_name
    DHWP_MBL[u'idx_ExpectedNumberOfShower']= domoticz_add_virtual_device_2(idx,u'0xF43E',Widget_name)
    option = u'TGV2ZWxOYW1lczpPZmZ8NjAlfDcwJXw4MCV8OTAlfDEwMCU7TGV2ZWxBY3Rpb25zOnx8fHx8O1NlbGVjdG9yU3R5bGU6MDtMZXZlbE9mZkhpZGRlbjp0cnVl'
    send=requests.get(u'http://'+domoticz_ip+u":"+domoticz_port+u'/json.htm?addjvalue=0&addjvalue2=0&customimage=0&description=&idx='+(DHWP_MBL[u'idx_ExpectedNumberOfShower'])+'&name='+Widget_name+'&options='+option+'&protected=false&strparam1=&strparam2=&switchtype=18&type=setused&used=true')
    
    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+Device_name+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(DHWP_MBL)

    print(u"Ajout: "+Device_name)
    return liste


def add_DHWP_MBL_CEEC (idx,liste,url,x,label):
    ''' Add CumulativeElectricPowerConsumptionSensor
    '''
    # Création du nom, celui contenu dans le JSON n'est pas compatible avec Domoticz (Modbuslink1#2)
    Device_name= u'Energy MBL'
	
    # Création du dictionnaire de définition du device
    DHWP_MBL_CEEC = {}
    DHWP_MBL_CEEC [u'url'] = url
    DHWP_MBL_CEEC [u'x']= x
    DHWP_MBL_CEEC [u'nom']= Device_name
    
    # Add : CumulativeElectricPowerConsumptionSensor (core:ElectricEnergyConsumptionState)
    Widget_name = u'Energy '+Device_name
    DHWP_MBL_CEEC[u'idx_ElectricEnergyConsumptionState']= domoticz_add_virtual_device(idx,113,Widget_name)
    
    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+Device_name+u" ,url: "+url)

    # ajout du dictionnaire dans la liste des device:
    liste.append(DHWP_MBL_CEEC)

    print(u"Ajout: "+Device_name)
    return liste

    

def ajout_bridge_cozytouch(idx,liste,url,x,label):
    nom = u'Bridge Cozytouch '+label

    # Log Domoticz :
    domoticz_write_log(u"Cozytouch : creation "+nom+u" ,url: "+url)

    print("Ajout: "+nom)
    return liste

'''
**********************************************************
Fonction de comparaison de consigne pour maj Domoticz
**********************************************************
'''

def gestion_consigne(texte,url_device,nom_device, idx_cons_domoticz, cons_device,cde_name,cons_device_abais_eco=0,cons_domoticz_confort=0,arrondi = True):
    ''' Compare les consignes de domoticz ancienne / actuelle / ainsi que celle du device
    pour déterminer qui demande un changement de consigne
    envoi le changement de consigne au device ou à Domoticz et inscrit un log
    '''
    texte= texte.decode("utf-8")
    idx_cons_domoticz= idx_cons_domoticz.encode("utf-8")
    cons_domoticz_prec = var_restore('save_consigne_'+(nom_device.encode("utf-8"))+idx_cons_domoticz)

    #Si Gestion di mode éco radiateur, on soustrait à la consigne confort (cons_device) , la consigne éco (cons_device_eco) :
    if cons_device_abais_eco >0 :
        cons_device_confort = cons_device # Sauvegarde consigne cozytouch confort
        cons_device_eco = cons_device - cons_device_abais_eco # Calcul consigne cozytouch éco
        cons_device = cons_device_eco # Application de la consigne éco pour le reste de la fonction

    # Calcul de l'écart de consigne
    # limitation consigne : la consigne n'accepte que des pas de 0,5°C
    # si la partie décimale est égale à 0,5 on accepte, sinon on arrondit
    cons_domoticz = domoticz_read_device_analog(idx_cons_domoticz)

    if arrondi :
        e = int(cons_domoticz)
        e = cons_domoticz - e
            # si la partie décimale est différente de 0,5°C on arrondit
        if e != 0.5:
            cons_domoticz = round(cons_domoticz)


    # comparaison avec la consigne en cours
    if cons_device != cons_domoticz and cons_domoticz != cons_domoticz_prec and cons_domoticz_prec > 0:
        # si un écart est détecté
        # et si le changement de consigne vient de domoticz, on envoie le changement au device
        # et si la consigne précédente est différente de 0 (cas au démarrage)

    # Si Gestion du mode éco radiateur :
        if cons_device_abais_eco > 0 :
            # On fait consigne confort Domoticz - consigne éco demandée par Domoticz (Cozytouch demande l'écart entre les deux)
            # On prend la consigne confort Domoticz pour le cas où l'on change les 2 consignes en meme temps
            cons_domoticz_abais_eco = cons_domoticz_confort - cons_domoticz
            # Valeur mini de l'écart de consigne = 2°C
            if cons_domoticz_abais_eco < 2 :
                cons_domoticz_abais_eco = 2 # Minimum 2°C
                cons_domoticz = cons_domoticz - cons_domoticz_abais_eco  # Ecriture de la consigne Domoticz
                domoticz_write_device_analog(cons_domoticz,idx_cons_domoticz) # Mise à jour de la consigne Domoticz
                domoticz_write_log(u'Cozytouch - '+nom_device+u' : consigne '+texte+u' : consigne doit etre 2°C en dessous de la consigne confort ! ')

                print "consigne abaissement éco Domoticz " + str(cons_domoticz_abais_eco)
            cozytouch_POST(url_device,cde_name,cons_domoticz_abais_eco) # Envoi de la consigne limitée à Cozytouch
            var_save(cons_domoticz, ('save_consigne_'+(nom_device.encode("utf-8"))+idx_cons_domoticz)) # Sauvegarde consigne domoticz
        else :
            cozytouch_POST(url_device,cde_name,cons_domoticz)
        var_save(cons_domoticz, ('save_consigne_'+(nom_device.encode("utf-8"))+idx_cons_domoticz))
        domoticz_write_log(u'Cozytouch - '+nom_device+u' : nouvelle consigne '+texte+u' transmise: '+str(cons_domoticz)+u'°C')

        if debug:
            print('Fonction gestion_consigne : Chgt consigne Domoticz, envoie vers Cozytouch : '+(nom_device.encode("utf-8"))+'/'+(texte.encode("utf-8"))+'/'+str(cons_domoticz)+'°C')

    elif cons_device != cons_domoticz and cons_domoticz == cons_domoticz_prec and cons_domoticz_prec > 0:
        # sinon, le changement vient du device Cozytouch
        # mise à jour de domoticz
        if debug:
            print('Fonction gestion_consigne : Chgt consigne Cozytouch, envoie vers Domoticz : '+(nom_device.encode("utf-8"))+'/'+(texte.encode("utf-8"))+'/'+str(cons_device)+'°C')
    # Si Gestion du mode éco radiateur :
        domoticz_write_log(u'Cozytouch - '+nom_device+u' : detection changement consigne ' +texte+' : '+str(cons_device)+u'°C')
        domoticz_write_device_analog(cons_device,idx_cons_domoticz)
        var_save(cons_device, ('save_consigne_'+(nom_device.encode("utf-8"))+idx_cons_domoticz))

    else :
        # ou simple rafraichissement domoticz si aucun changement
        if debug:
            print('Fonction gestion_consigne : Rafraichissement consigne : '+(nom_device.encode("utf-8"))+'/'+(texte.encode("utf-8"))+'/'+str(cons_device)+'°C')
        domoticz_write_device_analog(cons_device,idx_cons_domoticz)
        var_save(cons_device, ('save_consigne_'+(nom_device.encode("utf-8"))+idx_cons_domoticz))


def gestion_switch_selector_domoticz (cozytouch_mode_actual, url_device, nom_device, idx_switch_domoticz,state_cozytouch_on_off='no',
                                                 command_off_activate= False,setting_command_on_off=u'setOperatingMode',setting_parameter_off=u'standby',
                                                 command_on_activate = False, setting_parameter_on='on',
                                                 command_manual_activate = False, manual_level=10,setting_command_manual=u'setDerogatedMode', setting_parameter_manual_on=u'on',setting_parameter_manual_off=u'off',
                                                 level_0=u'0',level_10=u'10',level_20=u'20',level_30=u'30',level_40=u'40',level_50=u'50', level_60=u'60',level_70=u'70',level_80=u'80',setting_command_mode=u'setting_mode',
                                                 command_activate=True):
    
    # Comparaison avec l'état précédent pour mettre à jour uniquement sur changement (évite de remplir les logs inutilement)
    # Lecture de l'état précédent du level du switch de domoticz :
    domoticz_switch_actual = domoticz_read_device_switch_selector(idx_switch_domoticz)
    domoticz_mode_old = var_restore('save_'+str(idx_switch_domoticz),format_str=True) # On demande une initialisation avec 'init'

    if debug:
        print( "Fonction comparaison switch selecteur : "+ nom_device+' idx:'+idx_switch_domoticz)

    # Association du level actuel du swith avec les noms définis en paramètres :
    # Utilisation ou non de la variable 'on_off', si oui, utilisation si 'on_off' = 'off' pour le level_0 du switch
    if domoticz_switch_actual == 0 :
        domoticz_mode_actual = level_0
    if domoticz_switch_actual == 10:
        domoticz_mode_actual = level_10
    if domoticz_switch_actual == 20:
        domoticz_mode_actual = level_20
    if domoticz_switch_actual == 30:
        domoticz_mode_actual = level_30
    if domoticz_switch_actual == 40:
        domoticz_mode_actual = level_40
    if domoticz_switch_actual == 50:
        domoticz_mode_actual = level_50
    if domoticz_switch_actual == 60:
        domoticz_mode_actual = level_60
    if domoticz_switch_actual == 70:
        domoticz_mode_actual = level_70
    if domoticz_switch_actual == 80:
        domoticz_mode_actual = level_80
        
    if command_off_activate and state_cozytouch_on_off == setting_parameter_off : # Device à OFF : Si état lu de cozytouch = état  OFF
        cozytouch_mode_actual = level_0
        domoticz_switch_state_to_send = 0

    else :
        domoticz_switch_state_to_send = 0 # par defaut chargement switch à 0
        if cozytouch_mode_actual == level_10:
            domoticz_switch_state_to_send = 10
        if cozytouch_mode_actual == level_20:
            domoticz_switch_state_to_send = 20
        if cozytouch_mode_actual == level_30 :
            domoticz_switch_state_to_send = 30
        if cozytouch_mode_actual == level_40 :
            domoticz_switch_state_to_send = 40
        if cozytouch_mode_actual == level_50 :
            domoticz_switch_state_to_send = 50
        if cozytouch_mode_actual == level_60 :
            domoticz_switch_state_to_send = 60
        if cozytouch_mode_actual == level_70 :
            domoticz_switch_state_to_send = 70
        if cozytouch_mode_actual == level_80 :
            domoticz_switch_state_to_send = 80

    if debug:
        print("Etat actuel du switch Domoticz: "+str(domoticz_switch_actual))
        print("Etat actuel du mode dans Domoticz: "+str(domoticz_mode_actual))
        print("Etat ancien du mode dans Domoticz: "+str(domoticz_mode_old))
        print("Etat actuel du mode dans Cozytouch: "+str(cozytouch_mode_actual))

    # Comparaison du mode en cours de cozytouch et du mode en cours de domoticz
    if cozytouch_mode_actual != domoticz_mode_actual and domoticz_mode_old != 'init':
        # Cas 1 : Comparaison du mode en cours de domoticz avec le mode précédent en mémoire, si différent :
        # le changement de mode vient de domoticz, on envoie le nouveau mode àv cozytouch
        if domoticz_mode_actual != domoticz_mode_old :
            if debug:
                print("Cas 1 : changement vient de domoticz, envoie du mode à cozytouch")

            # Options de commandes on/off :
            if command_off_activate :
                #Envoi de la commande 'OFF'
                if domoticz_switch_actual == level_0 :
                    cozytouch_POST(url_device,setting_command_on_off,setting_parameter_off)
                #Envoi de la commande 'ON'
                elif command_on_activate :
                    cozytouch_POST(url_device,setting_command_on_off,setting_parameter_on)

            # Options de commandes Manuel :
            if command_manual_activate :
                #Envoi de la commande 'Dérogation : on'. Sortie de la fonction avec valeur de retour pour traitement hors fonction des commandes à envoyer.
                if domoticz_switch_actual == manual_level :
                    domoticz_write_log('Cozytouch - '+nom_device+' : nouveau mode transmis: '+str(domoticz_mode_actual))
                    var_save(domoticz_mode_actual, ('save_'+str(idx_switch_domoticz)))
                
                else : #Envoi de la commande 'Dérogation : off'
                    cozytouch_POST(url_device,setting_command_manual,setting_parameter_manual_off)
                
            #Envoi de la commande par défaut
            if command_activate :
                cozytouch_POST(url_device,setting_command_mode,domoticz_mode_actual)

            domoticz_write_log('Cozytouch - '+nom_device+' : nouveau mode transmis: '+str(domoticz_mode_actual))
            var_save(domoticz_mode_actual, ('save_'+str(idx_switch_domoticz)))
            return (1,domoticz_mode_actual)

        # Cas 2 : Comparaison de l'état actuel domoticz avec l'état précédent en mémoire, si identique :
        # le changement de mode vient de cozytouch, on envoie le mode à domoticz
        elif domoticz_mode_actual == domoticz_mode_old :
            if debug:
                print("Cas 2 : changement de mode vient de cozytouch, on envoie le mode à domoticz")
            domoticz_write_log('Cozytouch - '+nom_device+' : detection changement mode ' +str(cozytouch_mode_actual ))
            domoticz_write_device_switch_selector(domoticz_switch_state_to_send ,idx_switch_domoticz)
            var_save(cozytouch_mode_actual, ('save_'+str(idx_switch_domoticz)))
            return (2,cozytouch_mode_actual)

    elif  domoticz_mode_old=='init' :
        # Domoticz non initialisé
        if debug:
             print("Cas 4 : initialisation du  mode dans Domoticz")
        domoticz_write_device_switch_selector(domoticz_switch_state_to_send,idx_switch_domoticz)
        var_save(cozytouch_mode_actual, ('save_'+str(idx_switch_domoticz)))
        return (4,cozytouch_mode_actual)

    else :
        # Cozytouch et Domoticz synchronisés aucun changement
        if debug :
            print("Cas 3 : aucun changement de mode, aucune action")
        return (3,cozytouch_mode_actual)

    
def value_by_name(data,device,item):
    for state in data['setup']['devices'][device]['states']:
        if state['name'] == item:
            return state['value']
    print('Failed to retrieve value '+item+' for device '+data['setup']['devices'][device]['widget'])
    return None


def maj_device(data,name,p,x):

    ''' Fonction de mise à jour du device dans Domoticz
    '''

    print("Mise a jour device "+str(p)+" : "+name +" /x: "+ str(x))
    a = var_restore('save_devices')
    classe = a[p]
    
    ''' Mise à jour : Données radiateur
    '''
    if name == dict_cozytouch_devtypes.get(u'module fil pilote') or  name == dict_cozytouch_devtypes.get(u'radiateur') :
        # Switch selecteur mode OFF / Manuel / Auto
        gestion_switch_selector_domoticz ((value_by_name(data,x,u'io:TargetHeatingLevelState')),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_level'),
                                                         state_cozytouch_on_off=((value_by_name(data,x,u'core:OperatingModeState'))), command_off_activate = True,
                                                         level_0=u'off',level_10=u'frostprotection',level_20=u'eco',level_30=u'comfort-2',level_40=u'comfort-1',level_50=u'comfort',setting_command_mode=u'setHeatingLevel')

    if name == dict_cozytouch_devtypes.get(u'radiateur') :
        # Switch selecteur mode ordre radiateur OFF / Hors gel / Eco / Confort -2 / Confort -2 / Confort
        # pas d'écriture possible depuis domoticz pour un radiateur connecté, l'ordre est imposé par le fil pilote ou le mode de programmation interne de l'appareil

        # Lecture de l'ordre en cours sur le radiateur :
        ordre_radiateur = (value_by_name(data,x,u'io:TargetHeatingLevelState'))
        #Lecture de l'état de fonctionnement du radiateur :
        mode_radiateur=(value_by_name(data,x,u'core:OperatingModeState'))

        # Switch selecteur mode OFF / Manuel / Auto
        gestion_switch_selector_domoticz (value_by_name(data,x,u'core:OperatingModeState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                     level_0=u'standby',level_10=u'basic',level_20=u'internal',level_30=u'Derogation',setting_command_mode=u'setOperatingMode')

        # Mesure température : Device : TemperatureSensor, Parametre 1 : core:TemperatureState
        domoticz_write_device_analog((value_by_name(data,(x+1),u'core:TemperatureState')),(classe.get(u'idx_mesure_temp')))

        # Consigne de température confort : Device : AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent, Parametre 9 : core:ComfortRoomTemperatureState
        gestion_consigne(u'confort',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_confort'),value_by_name(data,x,u'core:ComfortRoomTemperatureState'),(u'setComfortTemperature'))

        # Consigne de témpérature éco : Device : AtlanticElectricalHeaterWithAdjustableTemperatureSetpointIOComponent, Parametre 10: core:EcoRoomTemperatureState
        gestion_consigne(u'eco',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_eco'),value_by_name(data,x,'core:ComfortRoomTemperatureState') ,u'setSetpointLoweringTemperatureInProgMode',
                         cons_device_abais_eco = value_by_name(data,x,u'io:SetpointLoweringTemperatureInProgModeState'), # lecture de la consigne éco appliquée par Cozytouch
                         cons_domoticz_confort = domoticz_read_device_analog(classe.get(u'idx_cons_temp_confort'))) # lecture de la consigne confort appliquée dans Domoticz

        # Compteur d'énergie: Device : CumulativeElectricPowerConsumptionSensor, Parametre 1 : core:ElectricEnergyConsumptionState
        domoticz_write_device_analog((value_by_name(data,x+4,u'core:ElectricEnergyConsumptionState')),(classe.get(u'idx_compteur')))

    ''' Mise à jour : Données chauffe eau
    '''
    if name == dict_cozytouch_devtypes.get('chauffe eau'):

        # Switch on/off
        on_off = (value_by_name(data,x,"io:OperatingModeCapabilitiesState")[u'energyDemandStatus'])
        if on_off == 1 :
            on_off = 'On'
        else:
            on_off = 'Off'
        # Comparaison avec l'état précédent pour mettre à jour uniquement sur changement (évite de remplir les logs inutilement)
        onoff_prec = var_restore('save_onoff_'+str(classe.get('idx_on_off')))
        if onoff_prec != on_off :
            domoticz_write_device_switch_onoff(on_off,(classe.get('idx_on_off')))
            var_save(on_off, ('save_onoff_'+str(classe.get('idx_on_off'))))

        # Switch selecteur auto/manu/manu+eco : définition des levels du switch
        auto_manu = value_by_name(data,x,"io:DHWModeState")
        if auto_manu == 'autoMode':
            switch = 0
        if auto_manu == 'manualEcoInactive':
            switch = 10
        if auto_manu == 'manualEcoActive':
            switch = 20

        # Switch selecteur :
        # Comparaison avec l'état précédent pour mettre à jour uniquement sur changement (évite de remplir les logs inutilement)
        switch_prec = var_restore('save_switch_'+str(classe.get('idx_switch_auto_manu')))
        if switch_prec != switch :
            domoticz_write_device_switch_selector(switch, classe.get('idx_switch_auto_manu'))
            var_save(switch, ('save_switch_'+str(classe.get('idx_switch_auto_manu'))))

        # Mesure température :
        domoticz_write_device_analog((value_by_name(data,x,"core:TemperatureState")),(classe.get('idx_mesure_temp')))

        # Compteur d'eau chaude restante :
        domoticz_write_device_analog(value_by_name(data,x,"core:WaterConsumptionState"),(classe.get('idx_conso_eau')))

        # Calcul puissance moyenne :
        wh_prec = var_restore('wh_prec_'+str(classe.get('idx_compteur')))
        wh_actuel = value_by_name(data,x+1,'core:ElectricEnergyConsumptionState')
        wh_1min = wh_actuel - wh_prec
        Pmoy_1min = wh_1min * 60
        var_save(wh_actuel, ('wh_prec_'+str(classe.get('idx_compteur'))))

        # Compteur d'énergie:
        domoticz_write_device_analog(str(Pmoy_1min)+';'+str(wh_actuel),(classe.get('idx_compteur')))

        # Compteur temps de fonctionnement pompe à chaleur :
        domoticz_write_device_analog((value_by_name(data,x,"io:HeatPumpOperatingTimeState")),(classe.get('idx_compteur_pompe')))

    ''' Mise à jour : Données PAC
    '''
    if name == dict_cozytouch_devtypes.get(u'PAC main control') :

        # MAJ données générales PAC

        # Lecture du mode stop/heating/cooling/drying :
        global mode_PAC
        mode_PAC = (value_by_name(data,x,u'io:PassAPCOperatingModeState'))
        # Lecture du mode auto :  Remplacement variable mode par 'auto'
        if value_by_name(data,x,u'core:HeatingCoolingAutoSwitchState')== u'on':
            mode_PAC = u'auto'
        # Gestion du sélecteur :
        # Voir comment gérer la demande de passage en mode auto, il faut adresser une commande "setHeatingCoolingAutoSwitch" au changement du label u'auto'
        # BLOC MODIFIE POUR ENVOI D ELA COMMANDE SETHEATINGCOLLINGAUTOSWITCH MAIS IL FAUT ENVOYER UN 'ON' OU UN 'OFF' PAS LE LABEL 40 'AUTO'
        gestion_switch_selector_domoticz (mode_PAC,classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                     level_0='stop',level_10='heating',level_20='cooling',level_30='drying',level_40='auto',setting_command_mode='setPassAPCOperatingMode',
                                                     special_level = 'auto',special_setting='setHeatingCoolingAutoSwitch',special_setting_parameter_on='on',special_setting_parameter_off='off')

    if name == dict_cozytouch_devtypes.get('PAC zone control') :
        # MAJ données zone PAC

        # Mesure température :
        domoticz_write_device_analog(value_by_name(data,(x+1),u'core:TemperatureState'),classe.get(u'idx_mesure_temp'))

        # Consigne température Confort en mode chauffage en mode programmation : (core:ComfortHeatingTargetTemperatureState)
        gestion_consigne(u'Confort chauff.',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_confort_chauffage'),value_by_name(data,x,u'core:ComfortHeatingTargetTemperatureState'),(u'setComfortHeatingTargetTemperature'))

        # Consigne température Confort mode climatisation en mode programmation : (core:ComfortCoolingTargetTemperatureState)
        gestion_consigne(u'Confort rafraich.',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_confort_clim'),value_by_name(data,x,u'core:ComfortCoolingTargetTemperatureState'),(u'setComfortCoolingTargetTemperature'))

        # Consigne température Eco mode chauffage en mode programmation : (core:EcoHeatingTargetTemperatureState)
        gestion_consigne(u'Eco chauff.',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_eco_chauffage'),value_by_name(data,x,u'core:EcoHeatingTargetTemperatureState'),(u'setEcoHeatingTargetTemperature'))

        # Consigne température Confort mode climatisation en mode programmation : (core:EcoCoolingTargetTemperatureState)
        gestion_consigne(u'Eco rafraich.',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_eco_clim'),value_by_name(data,x,u'core:EcoCoolingTargetTemperatureState'),(u'setEcoCoolingTargetTemperature'))

        # Switch selecteur mode OFF / Manuel / Auto
        # dépendant du mode en cours de la Zone Control pour le mode Manuel

        # Si zone Control en mode 'Heating' :
        if mode_PAC == u'heating' :
            # Gestion consigne en mode manuel : Seeting consigne en mode 'heating'
            setting_consigne_zone = u'setHeatingTargetTemperature'
            # Gestion switch sélecteur : Prise en compte du mode de fonctionnement de la  zone control 
            state_mode_zone = value_by_name(data,x,u'io:PassAPCHeatingModeState')
            # Gestion switch sélecteur : Setting mode en mode 'heating'
            setting_command_mode_zone  = u'setPassAPCHeatingMode'
            # Gestion switch sélecteur : Setting mode 'off' en mode 'heating'
            setting_command_on_off_mode_zone = u'setHeatingOnOffState'
            # Gestion switch sélecteur : Prise en compte de l'état de la zone (manu, comfort, eco...)
            state_zone = value_by_name(data,x,u'io:PassAPCHeatingProfileState')
            # Gestion switch sélecteur : Prise en compte de l'état on/off de la zone
            state_on_off_zone = value_by_name(data,x,u'core:HeatingOnOffState')

            # Gestion de la consigne manuel suivant l'état de fonctionnement de la PAC (heating ou cooling)
            # Consigne température en mode manu : (setCoolingTargetTemperature en mode manuel refroidissement / setHeatingTargetTemperature en mode manuel chauffage)
            gestion_consigne(u'Manuel',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_manu'),value_by_name(data,x,u'core:TargetTemperatureState'),setting_consigne_zone)

            # Gestion switch sélecteur :
            return_switch = gestion_switch_selector_domoticz (state_mode_zone ,classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                         state_cozytouch_on_off = state_on_off_zone,
                                                         command_off_activate= True, setting_command_on_off=setting_command_on_off_mode_zone, setting_parameter_off=u'off',
                                                         command_on_activate=True, setting_parameter_on=u'on',
                                                         level_0=u'stop',level_10=u'manu',level_20=u'internalScheduling',setting_command_mode=setting_command_mode_zone)

            # Evaluation du retour de la fonction, si cas n°2, on a envoyé un changement vers Cozytouch
            # On renvoi dans tous les cas de changement de mode vers Cozytouch la consigne manuel
            if return_switch == 1 :
                # Renvoi de la consigne de T°C manuel lors d'une changement de mode vers manuel (sinon sans cela, la consigne passe à 8°C, mystère Cozytouch)
                cozytouch_POST(classe.get(u'url'),setting_consigne_zone, domoticz_read_device_analog(classe.get(u'idx_cons_temp_manu')))

        # Si zone Control en mode 'Cooling' :
        elif mode_PAC == u'cooling':
            # Gestion consigne en mode manuel : Setting consigne en mode 'heating'
            setting_consigne_zone = u'setCoolingTargetTemperature'
            # Gestion switch sélecteur : Prise en compte du mode de fonctionnement de la  zone control suivant le paramètre de fonctionnement en mode 'cooling'
            state_mode_zone = value_by_name(data,x,u'io:PassAPCCoolingModeState')
            # Gestion switch sélecteur : Setting mode en mode 'cooling'
            setting_command_mode_zone = u'setPassAPCCoolingMode'
            # Gestion switch sélecteur : Setting mode 'off' en mode 'cooling'
            setting_command_on_off_mode_zone = u'setCoolingOnOffState'
            # Gestion switch sélecteur : Prise en compte de l'état de la zone (manu, comfort, eco...)
            state_zone = value_by_name(data,x,u'io:PassAPCCoolingProfileState')
            # Gestion switch sélecteur : Prise en compte de l'état on/off de la zone
            state_on_off_zone = value_by_name(data,x,u'core:CoolingOnOffState')

            # Gestion de la consigne manuel suivant l'état de fonctionnement de la PAC (heating ou cooling)
            # Consigne température en mode manu : (setCoolingTargetTemperature en mode manuel refroidissement / setHeatingTargetTemperature en mode manuel chauffage)
            gestion_consigne(u'Manuel',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_manu'),value_by_name(data,x,u'core:TargetTemperatureState'),setting_consigne_zone)

            # Gestion switch sélecteur :
            return_switch = gestion_switch_selector_domoticz (state_mode_zone ,classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                         state_cozytouch_on_off = state_on_off_zone,
                                                         command_off_activate= True, setting_command_on_off=setting_command_on_off_mode_zone, setting_parameter_off=u'off',
                                                         command_on_activate=True, setting_parameter_on=u'on',
                                                         level_0=u'stop',level_10=u'manu',level_20=u'internalScheduling',setting_command_mode=setting_command_mode_zone)

            # Evaluation du retour de la fonction, si cas n°2, on a envoyé un changement vers Cozytouch
            # On renvoi dans tous les cas de changement de mode vers Cozytouch la consigne manuel
            if return_switch == 1 :
                # Renvoi de la consigne de T°C manuel lors d'une changement de mode vers manuel (sinon sans cela, la consigne passe à 8°C)
                cozytouch_POST(classe.get(u'url'),setting_consigne_zone, domoticz_read_device_analog(classe.get(u'idx_cons_temp_manu')))

        # Si zone control en 'stop' : on force l'affichage des zones en 'off''
        elif mode_PAC == u'stop' :
            # Gestion switch sélecteur :
            gestion_switch_selector_domoticz (state_mode_zone ,classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                         state_cozytouch_on_off = u'stop', # force une lecture d'un état OFF
                                                         level_0=u'stop',level_10=u'manu',level_20=u'internalScheduling')

    ''' Mise à jour : Données PAC HeatPump
    '''
    if name == dict_cozytouch_devtypes.get(u'PAC_HeatPump'):
        # MAJ données générales PAC
        # Gestion du sélecteur :
        gestion_switch_selector_domoticz (value_by_name(data,x,u'io:PassAPCOperatingModeState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                     level_0='stop',level_10='heating',level_20='cooling',level_30='drying',level_40='auto',setting_command_mode='setPassAPCOperatingMode',
                                                     command_activate=True)
        
    ''' Mise à jour : Mesure T°C Exterieure PAC
    '''
    if name == dict_cozytouch_devtypes.get(u'PAC OutsideTemp') :
        # Mesure température extérieure :
        domoticz_write_device_analog(value_by_name(data,x,u'core:TemperatureState'),classe.get(u'idx_mesure_temp'))

    ''' Mise à jour : Mesure T°C Interieure PAC
    '''
    if name == dict_cozytouch_devtypes.get(u'PAC InsideTemp') :
        # Mesure température intérieure :
        domoticz_write_device_analog(value_by_name(data,x,u'core:TemperatureState'),classe.get(u'idx_mesure_temp'))

    ''' Mise à jour : Compteurs Energie
    '''
    if name == dict_cozytouch_devtypes.get(u'PAC Electrical Energy Consumption') :
        # Compteur d'énergie 1 :
        domoticz_write_device_analog((value_by_name(data,x,u'core:ConsumptionTariff1State')),(classe.get(u'idx_compteur_1')))
        # Compteur d'énergie 2 :
        domoticz_write_device_analog((value_by_name(data,x,u'core:ConsumptionTariff2State')),(classe.get(u'idx_compteur_2')))

    ''' Mise à jour : Données PAC Zone Component
    '''
    if name == dict_cozytouch_devtypes.get(u'PAC zone component') :

        # Consigne température Confort en mode chauffage en mode programmation : (core:ComfortHeatingTargetTemperatureState)
        gestion_consigne(u'Confort chauff.',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_confort_chauffage'),value_by_name(data,x,u'core:ComfortHeatingTargetTemperatureState'),(u'setComfortHeatingTargetTemperature'), arrondi = False)
        
        # Consigne température Eco mode chauffage en mode programmation : (core:EcoHeatingTargetTemperatureState)
        gestion_consigne(u'Eco chauff.',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_eco_chauffage'),value_by_name(data,x,u'core:EcoHeatingTargetTemperatureState'),(u'setEcoHeatingTargetTemperature'))
                
        # Gestion de la consigne manuel 
        gestion_consigne(u'Manuel',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp_manu'),value_by_name(data,x,u'core:DerogatedTargetTemperatureState'),(u'setDerogatedTargetTemperature' ))
        '''
        # Switch selecteur durée de dérogation
        gestion_switch_selector_domoticz (value_by_name(data,x,u'io:DerogationRemainingTimeState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_derog_duration'),
                                                    level_0=0, level_10=1, level_20=2, level_30=3, level_40=4, level_50=5, level_60=6,level_70=7,level_80=8,setting_command_mode=u'setDerogationTime')
                                                    '''
        
        # Gestion switch sélecteur : Prise en compte du mode de fonctionnement de la zone 
        state_mode_zone = value_by_name(data,x,u'io:PassAPCHeatingModeState')
        #print (u'state_mode_zone :' + str(state_mode_zone))
        # Gestion switch sélecteur : Setting mode en mode 'heating'
        setting_command_mode_zone  = u'setPassAPCHeatingMode'
        #print (u'setting_command_mode_zone :' + str(setting_command_mode_zone))
        # Gestion switch sélecteur : Setting mode 'off'
        setting_command_on_off_mode_zone = u'setHeatingOnOffState'
        #print (u'setting_command_on_off_mode_zone :' + str(setting_command_on_off_mode_zone))
        # Gestion switch sélecteur : Prise en compte de l'état de la zone (manu, comfort, eco...)
        state_zone = value_by_name(data,x,u'io:PassAPCHeatingProfileState')
        #print (u'state_zone:' + str(state_zone))
        # Gestion switch sélecteur : Prise en compte du mode de fonctionnement "Derogation" (on/off)
        state_derog_zone = value_by_name(data,x,u'core:DerogationOnOffState')
        #print (u'state_derog_zone :' + str(state_derog_zone))
        # Forcage de l'état Dérogation pour le sélecteur
        if state_derog_zone == u'on' :
            state_mode_zone = u'manu'
            
        # Gestion switch sélecteur : Prise en compte de l'état on/off de la zone
        state_on_off_zone = value_by_name(data,x,u'core:HeatingOnOffState')
        
        # Gestion switch sélecteur :
        return_switch = gestion_switch_selector_domoticz (state_mode_zone ,classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                     state_cozytouch_on_off = state_on_off_zone,
                                                     command_off_activate=False, setting_command_on_off=setting_command_on_off_mode_zone, setting_parameter_off=u'off',
                                                     command_on_activate=False, setting_parameter_on=u'on',
                                                     command_manual_activate = True, setting_command_manual=u'setDerogationOnOffState', setting_parameter_manual_on=u'on', setting_parameter_manual_off=u'off',
                                                     level_0=u'stop',level_10=u'manu',level_20=u'internalScheduling',setting_command_mode=setting_command_mode_zone,
                                                     command_activate=False)

        # Evaluation du retour de la fonction : cas n°1, envoi vers Coytouch, avec mode manuel. On envoie les 3 paramètres pour activer le mode manuel :
        if return_switch == (1, u'manu'):
            # 1-Renvoi de la consigne de T°C manuel 
            cozytouch_POST(classe.get(u'url'),u'setDerogatedTargetTemperature',domoticz_read_device_analog(classe.get(u'idx_cons_temp_manu')))
            time.sleep(0.3)
            # 2-Renvoi de la durée de dérogation
            cozytouch_POST(classe.get(u'url'),u'setDerogationTime',(domoticz_read_device_switch_selector(classe.get(u'idx_derog_duration'))/10))         
            time.sleep(0.3)
            # 3-Puis activation du mode Manuel (Dérogation)
            cozytouch_POST(classe.get(u'url'),u'setDerogationOnOffState',u'on')
	
    ####
    # Update function : SubClass DHWP_THERM_V3_IO, DHWP_THERM_IO, DHWP_THERM_V2_MURAL_IO

    if name == dict_cozytouch_devtypes.get(u'DHWP_THERM_V3_IO') or name == dict_cozytouch_devtypes.get(u'DHWP_THERM_IO') or name == dict_cozytouch_devtypes.get(u'DHWP_THERM_V2_MURAL_IO')  :

        # Etat chauffe on/off
        a = (value_by_name(data,x,u"io:OperatingModeCapabilitiesState"))[u'energyDemandStatus']
        if a == 1 :
            on_off = u'On'
        else:
            on_off = u'Off'
        # Comparaison avec l'état précédent pour mettre à jour uniquement sur changement (évite de remplir les logs inutilement)
        onoff_prec = var_restore('save_onoff_'+str(classe.get('idx_on_off')))
        if onoff_prec != on_off :
            domoticz_write_device_switch_onoff(on_off,classe.get(u'idx_on_off'))
            var_save(on_off, ('save_onoff_'+str(classe.get('idx_on_off'))))

        # Compteur temps de fonctionnement pompe à chaleur (io:HeatPumpOperatingTimeState)
        domoticz_write_device_analog(value_by_name(data,x,u'io:HeatPumpOperatingTimeState'),classe.get(u'idx_compteur_pompe'))

        # Energy counter (core:ElectricEnergyConsumptionState)
        domoticz_write_device_analog(value_by_name(data,x+1,u'core:ElectricEnergyConsumptionState'),classe.get(u'idx_compteur_energie'))

        # Consigne température (SetTargetTemperature) ou #'core:TemperatureState' si pb
        gestion_consigne (u'consigne',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_cons_temp'),value_by_name(data,x,u'core:TargetTemperatureState'),u'setTargetTemperature')

        # Remplacement état du chauffe eau par 'boost' si activé
        if (value_by_name(data,x,u"core:OperatingModeState"))[u'relaunch'] == u'on':
            state_chauffe_eau = u'boost'
        elif (value_by_name(data,x,u'core:OperatingModeState'))[u'absence'] == u'on':
            state_chauffe_eau = u'off'
        # Par défaut, état du chauffe eau repris sur le DHWmodeState (manual, manual+eco ou auto)
        else :
            state_chauffe_eau = (value_by_name(data,x,u'io:DHWModeState'))

        # Switch selecteur mode Manuel+ecoInactive/Manuel+ecoActive/Auto
        return_fonction = gestion_switch_selector_domoticz (state_chauffe_eau,classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_switch_mode'),
                                                     state_cozytouch_on_off = (value_by_name(data,x,u'core:OperatingModeState'))[u'absence'],
                                                     level_0=u'off',level_10=u'manualEcoInactive',level_20=u'manualEcoActive',level_30=u'autoMode',level_40=u'boost',setting_command_mode=u'setDHWMode',
                                                    command_activate=False)

        # Mode changement de domoticz vers Cozytouch avec nom du level envoyé
        if return_fonction[0] == 1 :
            if return_fonction[1]== u'off' :
                cozytouch_POST(classe.get(u'url'),u'setCurrentOperatingMode',u'{"absence":"on", "relaunch":"off"}')

            elif return_fonction[1] != u'off' and return_fonction[1] == u'boost' :
                cozytouch_POST(classe.get(u'url'),u'setCurrentOperatingMode',u'{"absence":"off", "relaunch":"on"}')

            elif return_fonction[1] != u'off' and return_fonction[1] != u'boost' :
                cozytouch_POST(classe.get(u'url'),u'setCurrentOperatingMode',u'{"absence":"off", "relaunch":"off"}')

            if return_fonction[1] == u'manualEcoInactive'  or return_fonction[1] == u'manualEcoActive'  or return_fonction[1] == u'autoMode'  :
                cozytouch_POST(classe.get(u'url'),u'setDHWMode',return_fonction[1])

        # Switch selecteur durée 'boost'
        gestion_switch_selector_domoticz (value_by_name(data,x,u'core:BoostModeDurationState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_boost_duration'),
                                                    level_0=0, level_10=1, level_20=2, level_30=3, level_40=4, level_50=5, level_60=6,level_70=7,setting_command_mode=u'setBoostModeDuration')

         # Switch selecteur durée 'absence'
        gestion_switch_selector_domoticz (int(value_by_name(data,x,u'io:AwayModeDurationState')),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_away_duration'),
                                                    level_0=0, level_10=1, level_20=2, level_30=3, level_40=4, level_50=5, level_60=6,level_70=7,setting_command_mode=u'setAwayModeDuration')

        ######
        # Update only for SubClass "DHWP_THERM_V2_MURAL_IO"
        if name == dict_cozytouch_devtypes.get(u'DHWP_THERM_V2_MURAL_IO')  :

            # Temperature measurement (io:MiddleWaterTemperatureState)
            domoticz_write_device_analog((value_by_name(data,x,u'io:MiddleWaterTemperatureState')),(classe.get(u'idx_temp_measurement')))

            # Heat Pump Energy Counter (io:PowerHeatPumpState)
            domoticz_write_device_analog((value_by_name(data,x,u'io:PowerHeatPumpState')),(classe.get(u'idx_energy_counter_heatpump')))

            # Heat Electrical Energy Counter (io:PowerHeatElectricalState)
            domoticz_write_device_analog((value_by_name(data,x,u'io:PowerHeatElectricalState')),(classe.get(u'idx_energy_counter_heatelec')))

            # Water volume estimation  (core:V40WaterVolumeEstimationState)
            domoticz_write_device_analog((value_by_name(data,x,u'core:V40WaterVolumeEstimationState')),(classe.get(u'idx_water_estimation')))

    ''' Mise à jour : DHWP_MBL
    '''
    if name == dict_cozytouch_devtypes.get(u'DHWP_MBL') :
        
        # Heating state (core:HeatingStatusState)
        if (value_by_name(data,x,u'core:HeatingStatusState')) == u'Heating' :
            HeatingStatusState = u'On'
        else:
             HeatingStatusState = u'Off'
        # Comparaison avec l'état précédent pour mettre à jour uniquement sur changement (évite de remplir les logs inutilement)
        onoff_prec = var_restore('save_onoff_'+str(classe.get(u'idx_HeatingStatusState')))
        if onoff_prec != HeatingStatusState :
            domoticz_write_device_switch_onoff(HeatingStatusState,classe.get(u'idx_HeatingStatusState'))
            var_save(HeatingStatusState, ('save_onoff_'+str(classe.get('idx_HeatingStatusState'))))


        # Temperature of water (modbuslink:MiddleWaterTemperatureState)
        domoticz_write_device_analog((value_by_name(data,x,u'modbuslink:MiddleWaterTemperatureState')),(classe.get(u'idx_MiddleWaterTemperatureState')))
        # Temperature of water (core:BottomTankWaterTemperatureState)
        domoticz_write_device_analog((value_by_name(data,x,u'core:BottomTankWaterTemperatureState')),(classe.get(u'idx_BottomTankWaterTemperatureState')))
        
        # Temperature of water (core:ControlWaterTargetTemperatureState)
        domoticz_write_device_analog((value_by_name(data,x,u'core:ControlWaterTargetTemperatureState')),(classe.get(u'idx_ControlWaterTargetTemperatureState')))
        
        # Water volume estimation (core:RemainingHotWaterState)
        domoticz_write_device_analog((value_by_name(data,x,u'core:RemainingHotWaterState')),(classe.get(u'idx_RemainingHotWaterState')))

        # Water volume estimation in percent 
        # Calculated ratio between "core:RemainingHotWaterState" in L and the maximum value observed for this item, designed by "capacity_tank"
        # capacity_tank = 206
        capacity = int(float(value_by_name(data,x,u'core:RemainingHotWaterState')))
        if capacity > var_restore('save_capacity_'+str(classe.get(u'idx_RemainingHotWaterState'))) :
            var_save(capacity, ('save_capacity_'+str(classe.get('idx_RemainingHotWaterState'))))
        
        capacity_tank = var_restore('save_capacity_'+str(classe.get(u'idx_RemainingHotWaterState')))
        domoticz_write_device_analog(int(float(value_by_name(data,x,u'core:RemainingHotWaterState'))/float(capacity_tank)*100),(classe.get(u'idx_RemainingHotWaterState_in_percent')))

        # Temperature Setpoint (core:WaterTargetTemperatureState / SetTargetTemperature) 
        gestion_consigne (u'consigne',classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_WaterTargetTemperature'),value_by_name(data,x,u'core:WaterTargetTemperatureState'),u'setWaterTargetTemperature')

        # Number of showers remaining (core:NumberOfShowerRemainingState)
        domoticz_write_device_analog((value_by_name(data,x,u'core:NumberOfShowerRemainingState')),(classe.get(u'idx_NumberOfShowerRemainingState')))

        # Expected Hot water Quantity requested only in manual mode, in % selector (60% (1 is sent),70% (2 is sent),80% (3 is sent),90% 4 is sent),100% (5 is sent))
        # (Data : core:ExpectedNumberOfShowerState / setExpectedNumberOfShower)
        gestion_switch_selector_domoticz (value_by_name(data,x,u'core:ExpectedNumberOfShowerState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_ExpectedNumberOfShower'),
                                                     level_10='1',level_20='2',level_30='3',level_40='4',level_50='5',
                                                     setting_command_mode='setExpectedNumberOfShower',command_activate=True)
        

        # Mode selector (auto/eco/manual) (Data : modbuslink:DHWModeState / setDHWMode)
        gestion_switch_selector_domoticz (value_by_name(data,x,u'modbuslink:DHWModeState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_Mode'),
                                                     level_0='autoMode',level_10='manualEcoInactive',level_20='manualEcoActive',
                                                     setting_command_mode='setDHWMode',command_activate=True)

        # Boost selector (Data : modbuslink:DHWBoostModeState / setBoostMode)
        gestion_switch_selector_domoticz (value_by_name(data,x,u'modbuslink:DHWBoostModeState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_DHWBoostModeState'),
                                                     level_0='off',level_10='on',
                                                     setting_command_mode='setBoostMode',command_activate=True)

        # Absence selector (Data : modbuslink:DHWAbsenceModeState / setAbsenceMode)
        return_switch = gestion_switch_selector_domoticz (value_by_name(data,x,u'modbuslink:DHWAbsenceModeState'),classe.get(u'url'),classe.get(u'nom'),classe.get(u'idx_DHWAbsenceModeState'),
                                                     level_0='off',level_10='on',
                                                     setting_command_mode='setAbsenceMode',command_activate=False)

        # Evaluation of function return : Case n°1 : Absence mode activation request from Domoticz
        if return_switch == (1, u'on'):
            # 1-Reading actual system time
            dt=datetime.datetime.now()
            # 2-Building JSON data with start time, equal to actual time
            start_time = json.dumps({"hour":dt.hour,"month":dt.month,"second":dt.second,"weekday":dt.weekday(),"year":dt.year,"day":dt.day,"minute":dt.minute})
            # 2-Sending Start Date
            cozytouch_POST(classe.get(u'url'),u'setAbsenceStartDate',start_time)
            # 3-Building JSON data with end time, equal to start time + 1year
            end_time = json.dumps({"hour":dt.hour,"month":dt.month,"second":dt.second,"weekday":dt.weekday(),"year":dt.year+1,"day":dt.day,"minute":dt.minute})
            # Time sleep
            time.sleep(0.3)
            # 4-Sending End Date
            cozytouch_POST(classe.get(u'url'),u'setAbsenceEndDate',end_time)
            # Time sleep
            time.sleep(3)
            # 5-Sending Absence Mode
            cozytouch_POST(classe.get(u'url'),u'setAbsenceMode',u'on')

       # Evaluation of function return : Case n°1 : Absence mode stop request from Domoticz
        if return_switch == (1, u'off'):
            cozytouch_POST(classe.get(u'url'),u'setAbsenceMode',u'off')
            


            

    ''' Mise à jour : DHWP_MBL_CEEC
    '''
    if name == dict_cozytouch_devtypes.get(u'DHWP_MBL_CEEC') :

        # CumulativeElectricPowerConsumptionSensor (core:ElectricEnergyConsumptionState)
        domoticz_write_device_analog((value_by_name(data,x,u'core:ElectricEnergyConsumptionState')),(classe.get(u'idx_ElectricEnergyConsumptionState')))
    
'''
**********************************************************
Déroulement du script
**********************************************************
'''
print("¤¤¤¤ Demarrage script cozytouch <=> domoticz version "+str(version)+" (debug :"+str(debug)+")")

pvma = sys.version_info.major
pvmi = sys.version_info.minor
pvmu = sys.version_info.micro
if debug:
    print("Version python : "+str(pvma)+"."+str(pvmi)+"."+str(pvmu))

if not (pvma == 2 and  pvmi== 7):
    print("!!!! Echec test version python, ce script nécessite python 2.7.x (idealement 2.7.15)")
    sys.exit(errno.ENOENT)

# Test de présence du fichier de sauvegarde cozytouch et virtual hardware
if test_exist_cozytouch_domoticz_hw_and_backup_store():
    print("Test présence du fichier de sauvegarde cozytouch et virtual hardware domoticz OK\n")

    # Test d'une requete GET pour voir si on peut se connecter avec l'ancien cookie et éviter le login
    print("**** Tentative interrogation serveur Cozytouch sans login, avec cookie login précédent ****")
    if cozytouch_GET('refreshAllStates'):
        print( "Requete de test sans login reussie, bypass login\n")
    else:
        # Tentative de login au serveur Cozytouch
        print("!!!! Echec interrogation serveur Cozytouch sans login, connexion serveur Cozytouch ****")

        if cozytouch_login(login,password):
            print("Connexion serveur Cozytouch reussie")

        else:
            print("!!!! Echec connexion serveur Cozytouch")
            sys.exit(errno.ECONNREFUSED)

        # Rafraichissement états
        if cozytouch_GET('refreshAllStates'):
            print("Requete refreshAllStates reussie")
        else:
            print("!!!! Echec requete refreshAllStates")
            sys.exit(errno.EPROTO)

    time.sleep(2)
    decouverte_devices()
    sys.exit(0)

else:
    print("!!!! Echec test presence fichier de sauvegarde cozytouch et virtual hardware domoticz")
    sys.exit(errno.ENOENT)

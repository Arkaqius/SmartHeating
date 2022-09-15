
__author__ = 'Arkaqius'
#WAM values
from math import nan
from random import randint
import operator

'''
Offset smaller than 0 -> smaller flow
Offset bigger than 0 -> bigger flow
'''

NOMINAL_FLOW_TEMP       = 45
RAD_ENFORCE_THRS        = 0.8
WAM_PARAMS              = [0.1,0.1,0.3,0.2,0.1,0.1,0.1]
WARM_FALG_OFFSET        = 2
FREZZING_FLAG_OFFSET    = 2
#Radiators offset
NUM_OF_RADIATORS        = 4
MAX_RADS_EFFECT_OFFSET  = 4
MAX_SINGLE_RAD_OFFSET   = 4
LOGGING_FLAG            = True

#Function to calculate weighten mean
def sh_wam(temperatures,weights):
    mean = nan
    if len(temperatures) == len(weights):
        mean = 0
        for idx,temp in enumerate(temperatures):
            mean = mean + temp * weights[idx]
        mean = mean/sum(weights)
    return mean

def sh_get_wam_temperatures():
    wam_temp = []
    #Get living room temperature
    wam_temp.append(sh_stub_gettemp())
    #Get Kitchen temperature
    wam_temp.append(sh_stub_gettemp())
    #Get Bathroom temperature
    wam_temp.append(sh_stub_gettemp())
    #Get Upper bathroom temperature
    wam_temp.append(sh_stub_gettemp())
    #Get UpperCorridor temperature
    wam_temp.append(sh_stub_gettemp())
    #Get Corridor temperature
    wam_temp.append(sh_stub_gettemp())
    #Get Entrance temperature
    wam_temp.append(sh_stub_gettemp())
    return wam_temp

def sh_get_wam_setpoints():
    setpoints = []
    #Get living room temperature
    setpoints.append(21)
    #Get Kitchen temperature
    setpoints.append(21)
    #Get Bathroom temperature
    setpoints.append(21)
    #Get Upper bathroom temperature
    setpoints.append(21)
    #Get UpperCorridor temperature
    setpoints.append(21)
    #Get Corridor temperature
    setpoints.append(21)
    #Get Entrance temperature
    setpoints.append(21)
    return setpoints

#Main smart heating event loop
def sh_main_loop():
    #Init all offsets
    freezing_flag = False
    curr_flow_temp = 0
    off_wam = 0
    off_warm_flag = 0
    off_frezzing = 0
    off_radiators = 0
    
    off_final = 0
    #Collect all neccessary values
    wam_temp        = sh_get_wam_temperatures()
    wam_set_points  = sh_get_wam_setpoints()
    warm_flag       = sh_stub_get_warm_flag()
    freezing_flag   = sh_get_freezing_flag()
    curr_flow_temp  = sh_get_flow_temp()
    #Calculate WAM
    off_wam = sh_wam(list(map(operator.sub, wam_set_points, wam_temp)) ,WAM_PARAMS)
    #Check warm in flag
    if(warm_flag):
        off_warm_flag = WARM_FALG_OFFSET
    #Check freezing forecast
    if(freezing_flag):
        off_frezzing = FREZZING_FLAG_OFFSET
    #Check flow temp
    if(curr_flow_temp < NOMINAL_FLOW_TEMP*RAD_ENFORCE_THRS):
        #Check radiators temperatures 
        off_radiators = sh_determinate_radiators_flag()
    
    #Calculate final offset
    off_final =  off_wam + off_warm_flag + off_frezzing + off_radiators
    #Logging
    if(LOGGING_FLAG):
        print(off_final)

    #Update thermostat offset

def sh_determinate_radiators_flag():
    error = 0
    #Get radiators errors
    error += max(sh_stub_get_rad_set_point() - sh_stub_get_rad_temp(),0)
    error += max(sh_stub_get_rad_set_point() - sh_stub_get_rad_temp(),0)
    #Determinate offset
    return sh_dtrmnt_offset(error)

def sh_get_curr_setpoint():
    return 21

def sh_get_flow_temp():
    return randint(30,50)
def sh_dtrmnt_offset(error):
    return MAX_RADS_EFFECT_OFFSET * (error/(MAX_SINGLE_RAD_OFFSET*NUM_OF_RADIATORS))

def sh_stub_get_rad_set_point():
    return 21

def sh_stub_get_rad_temp():
    return randint(18,23)

def sh_stub_gettemp():
    return randint(15,25)

def sh_stub_get_warm_flag():
        return randint(0,1)
#TODO
def sh_get_freezing_flag():
    return False

def sh_get_current_offset():
    return 23


#TESTING
sh_main_loop()
import datetime
import hassapi as hass

__author__ = 'Arkaqius'

#Constants
CYCLE_TIME = 30 #[s] 

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
WAM_PARAMS              = [0.25,0.25,0.25,0.25]
WARM_FALG_OFFSET        = 2
FREZZING_FLAG_OFFSET    = 2
#Radiators offset
NUM_OF_RADIATORS        = 4
MAX_RADS_EFFECT_OFFSET  = 4
MAX_SINGLE_RAD_OFFSET   = 4
LOGGING_FLAG            = True

class SmartHeat(hass.Hass):
    def initialize(self):
        start_time = self.datetime() + datetime.timedelta(seconds=CYCLE_TIME)
        self.handle = self.run_every(self.sh_main_loop,start_time,CYCLE_TIME)
        #Initalize callbacks
        self.listen_state(self.setpoint_update, "input_number.sh_garage_setpoint", devices=['climate.garage_TRV'])
        self.listen_state(self.setpoint_update, "input_number.sh_bedroom_setpoint", devices=['climate.bedRoom_left_TRV','climate.bedRoom_right_TRV'])
        self.listen_state(self.setpoint_update, "input_number.sh_kidsroom_setpoint", devices=['climate.kidsroom_TRV'])
        self.listen_state(self.setpoint_update, "input_number.sh_office_setpoint", devices=['climate.office_TRV'])
        self.listen_state(self.setpoint_update, "input_number.sh_corridor_setpoint", devices=['number.thermostat_hc1_manual_temperature'])
    

        sensor.thermostat_hc1_manual_temperature

    #Setpoints mapping
    def setpoint_update(self, entity, attribute, old, new, kwargs):
        if 'TRV' in kwargs['devices'][0]:
            for dev in kwargs['devices']:
                entity = self.get_entity(dev)
                entity.call_service('set_temperature',temperature = new)

        else:
            entity = self.get_entity(dev)
            entity.call_service('set_number',value = new)

    #Main smart heating event loop
    def sh_main_loop(self):
        #Init all offsets
        freezing_flag = False
        curr_flow_temp = 0
        off_wam = 0
        off_warm_flag = 0
        off_frezzing = 0
        off_radiators = 0
        
        off_final = 0
        #Collect all neccessary values
        wam_temp        = self.sh_get_wam_temperatures()
        wam_set_points  = self.sh_get_wam_setpoints()
        warm_flag       = self.sh_get_warm_flag()
        freezing_flag   = self.sh_get_freezing_flag()
        curr_flow_temp  = self.sh_get_flow_temp()
        #Calculate WAM
        off_wam = self.sh_wam(list(map(operator.sub, wam_set_points, wam_temp)) ,WAM_PARAMS)
        #Check warm in flag
        if(warm_flag):
            off_warm_flag = WARM_FALG_OFFSET
        #Check freezing forecast
        if(freezing_flag):
            off_frezzing = FREZZING_FLAG_OFFSET
        #Check flow temp
        if(curr_flow_temp < NOMINAL_FLOW_TEMP*RAD_ENFORCE_THRS):
            #Check radiators temperatures 
            off_radiators = self.sh_determinate_radiators_flag()
        
        #Calculate final offset
        off_final =  off_wam + off_warm_flag + off_frezzing + off_radiators
        #Logging
        if(LOGGING_FLAG):
            self.log('Its working, somehow')
        #Update thermostat offset
        entity = self.get_entity('number.thermostat_hc1_offset_temperature')
        entity.call_service('set_number',value = off_final)
    
    #Function to calculate weighten mean
    def sh_wam(self,temperatures,weights):
        mean = nan
        if len(temperatures) == len(weights):
            mean = 0
            for idx,temp in enumerate(temperatures):
                mean = mean + temp * weights[idx]
            mean = mean/sum(weights)
        return mean 

    def sh_get_wam_temperatures(self):
        wam_temp = []
        #Get living room temperature
        wam_temp.append(self.my_enitity.get_state('sensor.livingroom_temperature'))
        #Get Kitchen temperature
        #wam_temp.append(self.my_enitity.get_state('sensor.livingroom_main_climatesensor_temperature'))
        #Get Bathroom temperature
        wam_temp.append(self.my_enitity.get_state('sensor.bathroom_temperature'))
        #Get Upper bathroom temperature
        wam_temp.append(self.my_enitity.get_state('sensor.upperbathroom_temperature')) 
        #Get UpperCorridor temperature
        #wam_temp.append(self.my_enitity.get_state('sensor.livingroom_main_climatesensor_temperature'))
        #Get Corridor temperature
        wam_temp.append(self.my_enitity.get_state('sensor.corridor_temperature'))
        #Get Entrance temperature
        #wam_temp.append(self.my_enitity.get_state('sensor.livingroom_main_climatesensor_temperature'))
        
        return wam_temp

    def sh_get_wam_setpoints(self):
        setpoints = []
        #Get living room temperature
        setpoints.append(self.my_enitity.get_state('input_number.sh_livingroom_setpoint'))
        #Get Kitchen temperature
        #setpoints.append(self.my_enitity.get_state('input_number.sh_bathroom_setpoint'))
        #Get Bathroom temperature
        setpoints.append(self.my_enitity.get_state('input_number.sh_bathroom_setpoint'))
        #Get Upper bathroom temperature
        setpoints.append(self.my_enitity.get_state('input_number.sh_upperbathroom_setpoint'))
        #Get UpperCorridor temperature
        #setpoints.append(self.my_enitity.get_state('input_number.sh_bathroom_setpoint'))
        #Get Corridor temperature
        setpoints.append(self.my_enitity.get_state('input_number.sh_bathroom_setpoint'))
        #Get Entrance temperature
        #setpoints.append(self.my_enitity.get_state('input_number.sh_bathroom_setpoint'))

        return setpoints

    def sh_determinate_radiators_flag(self):
        error = 0
        #Get radiators errors
        error += max(self.my_enitity.get_state('sensor.garage_temperatureError'),0)
        error += max(self.my_enitity.get_state('sensor.bedroom_temperatureError'),0)
        error += max(self.my_enitity.get_state('sensor.office_temperatureError'),0)
        error += max(self.my_enitity.get_state('sensor.kidsroom_temperatureError'),0)
        #Determinate offset
        return self.sh_dtrmnt_offset(error)

    def sh_get_curr_setpoint(self):
        return 21

    def sh_get_flow_temp(self):
        return self.my_enitity.get_state('sensor.boiler_current_flow_temperature')

    def sh_dtrmnt_offset(self,error):
        return MAX_RADS_EFFECT_OFFSET * (error/(MAX_SINGLE_RAD_OFFSET*NUM_OF_RADIATORS))

    #TODO
    def sh_get_freezing_flag(self):
        return False

    def sh_get_warm_flag(self):
        return self.my_enitity.get_state('input_boolean.sh_make_warmer')
#!../../bin/linux-x86_64/KOHUZ_ALV1

dbLoadDatabase "../../dbd/KOHUZ_ALV1.dbd"
KOHUZ_ALV1_registerRecordDeviceDriver(pdbbase)

## CA port: use 5070 to avoid conflict with soft_ioc (5064)
epicsEnvSet("EPICS_CAS_SERVER_PORT", "5070")

dbLoadTemplate("motor.substitutions")

## KOHZU ARIES at <YOUR_DEVICE_IP>:12321 (SW4 Device network)
drvAsynIPPortConfigure("L0", "<YOUR_DEVICE_IP>:12321", 0, 0, 0)

## CRLF line termination (required by KOHZU ARIES protocol)
asynOctetSetInputEos("L0", 0, "\r\n")
asynOctetSetOutputEos("L0", 0, "\r\n")

## Trace: error only (reduce log noise)
asynSetTraceIOMask("L0", 0, 0x2)
asynSetTraceMask("L0", 0, 0x1)

## Controller: PC0, port L0, 6 axes, movingPoll=0.2s, idlePoll=1.0s
KohzuAriesCreateController("PC0", "L0", 6, 0.2, 1.0)

iocInit()

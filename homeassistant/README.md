# sensor.delijn

A sensor that uses pyTheLine to show info from De Lijn.
  
To get started put `/custom_components/sensor/delijn.py` here:  
`<config directory>/custom_components/sensor/delijn.py`  
  
**Example configuration.yaml:**

```yaml
sensor:
  - platform: delijn
```

**Configuration variables:**  

| key | required | default | description
| --- | --- | --- | ---
| **platform** | yes | | The sensor platform name. 

## Sample overview

![Sample overview](overview.png)
  
***
Due to how `custom_componentes` are loaded, it is normal to see a `ModuleNotFoundError` error on first boot after adding this, to resolve it, restart Home-Assistant.

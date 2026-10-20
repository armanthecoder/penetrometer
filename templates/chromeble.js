const SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e;
var bluetoothDevice;

async function onScanButtonClick() {
  let options = {filters: []};

  let filterService = document.querySelector('#service').value;
  if (filterService.startsWith('0x')) {
    filterService = parseInt(filterService);
  }
  if (filterService) {
    options.filters.push({services: [filterService]});
  }

  let filterName = document.querySelector('#name').value;
  if (filterName) {
    options.filters.push({name: filterName});
  }

  let filterNamePrefix = document.querySelector('#namePrefix').value;
  if (filterNamePrefix) {
    options.filters.push({namePrefix: filterNamePrefix});
  }

  bluetoothDevice = null;
  try {
    log('Requesting Bluetooth Device...');
    bluetoothDevice = await navigator.bluetooth.requestDevice(options);
    bluetoothDevice.addEventListener('gattserverdisconnected', onDisconnected);
    connect();
  } catch(error) {
    log('Argh! ' + error);
  }
}

async function connect() {
  log('Connecting to Bluetooth Device...');
  await bluetoothDevice.gatt.connect();
  log('> Bluetooth Device connected');

return new Promise(async (resolve) => {
    console.log("Getting UART service");      
    var service = await bluetooth.getPrimaryService(USERVICE_ID);
    console.log("Getting characteristic");            
    var characteristic_tx = await service.getCharacteristic(TX_UUID);
    await characteristic_tx.startNotifications();
    characteristic_tx.addEventListener('characteristicvaluechanged', handleNotifications);    
  });


}
function handleNotifications(event) {
    let value = event.target.value;
    let decoder = new TextDecoder('utf-8');
    let str = decoder.decode(value);

    console.log(`Received notification: ${str}`);
    var newLogEntry = document.createElement("p");
    newLogEntry.textContent = str;    
    var loggingDiv = document.getElementById('logging-info');
    loggingDiv.appendChild(newLogEntry);    
}

function decode(encoded)
{
    var decoder = new TextDecoder('utf-8');
    var decoded_value = decoder.decode(encoded);
    return JSON.stringify(decoded_value)
}

function onDisconnectButtonClick() {
  if (!bluetoothDevice) {
    return;
  }
  log('Disconnecting from Bluetooth Device...');
  if (bluetoothDevice.gatt.connected) {
    bluetoothDevice.gatt.disconnect();
  } else {
    log('> Bluetooth Device is already disconnected');
  }
}

function onDisconnected(event) {
  // Object event.target is Bluetooth Device getting disconnected.
  log('> Bluetooth Device disconnected');
}

function onReconnectButtonClick() {
  if (!bluetoothDevice) {
    return;
  }
  if (bluetoothDevice.gatt.connected) {
    log('> Bluetooth Device is already connected');
    return;
  }
  try {
    connect();
  } catch(error) {
    log('Argh! ' + error);
  }
}
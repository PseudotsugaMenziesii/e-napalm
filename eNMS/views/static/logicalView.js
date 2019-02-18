/*
global
alertify: false
call: false
doc: false
*/

let selectedDevices = [];

function deviceToNode(device) {
  return {
    id: device.id,
    label: device.name,
    image: `static/images/default/${device.subtype}.gif`,
    shape: 'image'
  };
}

function linkToEdge(link) {
  return {
    from: link.source.id,
    to: link.destination.id,
  };
}

var nodes = new vis.DataSet(devices.map(deviceToNode));
var edges = new vis.DataSet(links.map(linkToEdge));

var container = document.getElementById('logical_view');
var data = {
  nodes: nodes,
  edges: edges,
};
var options = {};
var network = new vis.Network(container, data, options);

$('#select-filters').on('change', function() {
  call(`/inventory/pool_objects/${this.value}`, function(objects) {
    alertify.notify(`Filter applied.`, 'success', 5);
  });
});

(function() {
  doc('https://enms.readthedocs.io/en/latest/views/logical_view.html');
})();

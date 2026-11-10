.pragma library
function shortTime(date, clock24) {
    return Qt.formatDateTime(date, clock24 ? "HH:mm" : "h:mm AP").split(" ")[0];
}

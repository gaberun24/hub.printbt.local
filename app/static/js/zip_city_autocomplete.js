// Bidirekcionális irányítószám ↔ város autocomplete a Customer form-on.
//
// A teljes magyar irsz/település dataset-et (~75 KB, 3500 bejegyzés)
// betöltjük egyszer az első használatkor, és attól fogva a böngésző
// cache-eli. Két datalist + két input-listener:
//   - irányítószám → város: ha az adott zip-hez egy város tartozik, autofill
//   - város → irányítószám: ha az adott névhez egyetlen zip van, autofill
//     (Budapest-nél nem, mert 161 különböző zip)

(function () {
  var ZIP_INPUT_ID = "address-postal-code";
  var CITY_INPUT_ID = "address-city";
  var DATA_URL = "/static/data/hu_zips.json";

  var zipInput = document.getElementById(ZIP_INPUT_ID);
  var cityInput = document.getElementById(CITY_INPUT_ID);
  if (!zipInput || !cityInput) return;

  var zipToCity = null;     // {"1052": "Budapest", "2000": "Szentendre"}
  var cityToZips = null;    // {"Budapest": ["1007","1011",…], "Szentendre": ["2000"]}
  var allCities = null;     // sorted unique city names
  var loaded = false;

  function buildIndexes(rawData) {
    zipToCity = {};
    cityToZips = {};
    var citySet = {};
    for (var i = 0; i < rawData.length; i++) {
      var zip = rawData[i][0];
      var city = rawData[i][1];
      // Egy zip → egy város: ha véletlen több, az utolsó nyer
      // (a dataset-ben jellemzően egyedi)
      zipToCity[zip] = city;
      if (!cityToZips[city]) cityToZips[city] = [];
      cityToZips[city].push(zip);
      citySet[city] = true;
    }
    allCities = Object.keys(citySet).sort(function (a, b) {
      return a.localeCompare(b, "hu");
    });
  }

  function ensureLoaded() {
    if (loaded) return Promise.resolve();
    return fetch(DATA_URL, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        buildIndexes(data);
        loaded = true;
        populateDatalists();
      })
      .catch(function () {
        // Ha a dataset nem érhető el, a form simán működik manuális kitöltéssel
        loaded = false;
      });
  }

  function populateDatalists() {
    var zipList = document.getElementById("zip-datalist");
    if (zipList && zipList.children.length === 0) {
      var frag = document.createDocumentFragment();
      Object.keys(zipToCity).sort().forEach(function (zip) {
        var opt = document.createElement("option");
        opt.value = zip;
        opt.label = zipToCity[zip];
        opt.textContent = zipToCity[zip];
        frag.appendChild(opt);
      });
      zipList.appendChild(frag);
    }
    var cityList = document.getElementById("city-datalist");
    if (cityList && cityList.children.length === 0) {
      var frag2 = document.createDocumentFragment();
      allCities.forEach(function (city) {
        var opt = document.createElement("option");
        opt.value = city;
        frag2.appendChild(opt);
      });
      cityList.appendChild(frag2);
    }
  }

  // Zip → város autofill
  function onZipChange() {
    if (!loaded) return;
    var zip = (zipInput.value || "").trim();
    if (!zip) return;
    var city = zipToCity[zip];
    if (city && !cityInput.value.trim()) {
      cityInput.value = city;
    }
  }

  // Város → irsz autofill (csak ha egyetlen zip-je van a városnak)
  function onCityChange() {
    if (!loaded) return;
    var city = (cityInput.value || "").trim();
    if (!city) return;
    var zips = cityToZips[city];
    if (zips && zips.length === 1 && !zipInput.value.trim()) {
      zipInput.value = zips[0];
    }
  }

  // Listener-ek: change (mezőből kiugrás), input (autocomplete-választás)
  zipInput.addEventListener("change", onZipChange);
  zipInput.addEventListener("input", function () {
    // datalist-választáskor input-event jön a teljes value-val
    if (zipInput.value.length === 4) onZipChange();
  });
  cityInput.addEventListener("change", onCityChange);
  cityInput.addEventListener("input", function () {
    // ha a böngésző datalist-választást ad át (a teljes city kerül a value-be)
    if (cityToZips && cityToZips[cityInput.value]) onCityChange();
  });

  // Lazy load: az első fókuszra töltjük be a dataset-et
  zipInput.addEventListener("focus", ensureLoaded, { once: true });
  cityInput.addEventListener("focus", ensureLoaded, { once: true });
})();

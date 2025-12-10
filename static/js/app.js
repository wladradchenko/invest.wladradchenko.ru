// Main Application JavaScript - Portfolio Calculator

const API_BASE = "";
let currentIndexId = "";
let currentIndexName = "";
let excludedCount = 0;
let currentSecurities = [];
let selectedSecurities = {}; // {secid: {selected: bool, weight: number, price: number}}
let portfolioCapital = 0;
let loaderTimeout;
let selectedIndexes = []; // [{indexid, name, securities}]
const MAX_INDEXES = 3;
const MIN_WEIGHT_THRESHOLD = 0.3; // Минимальный вес для отображения (%)

// DOM Elements
const mainContent = document.getElementById("mainContent");
const loadingOverlay = document.getElementById("loadingOverlay");
const indexesStep = document.getElementById("indexesStep");
const securitiesStep = document.getElementById("securitiesStep");
const portfolioStep = document.getElementById("portfolioStep");
const indexesList = document.querySelector("#indexesList");
const indexesListCount = document.querySelectorAll(".indexes-count-text");
const indexesListCountPlural = document.querySelector(".indexes-count-text-plural");
const securitiesList = document.querySelector("#securitiesList");
const securitiesListCount = document.querySelectorAll(".securities-count-text");
const securitiesListCountPlural = document.querySelector(".securities-count-text-plural");
const securitiesStepHeader = document.querySelector("#securitiesStepHeader");
const portfolioResults = document.getElementById("portfolioResults");
const capitalInput = document.getElementById("capitalInput");
const calculateBtn = document.getElementById("calculateBtn");
const indexTitle = document.querySelector("#index-title");
const indexExcludedCount = document.querySelector("#index-excluded-count");
const securityModal = document.getElementById("securityModal");
const modalBody = document.getElementById("modalBody");
const modalClose = document.getElementById("modalClose");
const portfolioStepHeader = document.getElementById("portfolioStepHeader");


const TRANSLATIONS = {
  "Error loading indexes":"Ошибка загрузки индексов",
  "At least one index must be selected": "Должен быть выбран хотя бы один индекс",
  "You can select a maximum of": "Можно выбрать максимум",
  "indices": "индекса",
  "Indexes not found": "",
  "Error loading securities": "Ошибка загрузки бумаг",
  "Securities not found": "",
  "Excluded": "Исключено",
  "securities with weight less than": "бумаг с весом",
  "Large": "Крупные",
  "Medium": "Средние",
  "Small": "Мелкие",
  "Loading": "Загрузка",
  "Error": "Ошибка",
  "Buy": "Покупка", 
  "Sell": "Продажа",
  "Neutral": "Нейтрально",
  "Hold. The signals of the indicators are conflicting.": "Держать. Сигналы индикаторов разноречивые.",
  "strong": "слабый сигнал",
  "The signals of the majority of indicators are positive. The trend is strong.": "Сигналы большинства индикаторов положительные. Тренд сильный.",
  "weak": "сильный сигнал",
  "The signals of the majority of indicators are positive. The trend is weak.": "Сигналы большинства индикаторов положительные. Тренд слабый.",
  "The signals of the majority of indicators are negative. The trend is strong.": "Сигналы большинства индикаторов отрицательные. Тренд сильный.",
  "The signals of the majority of indicators are negative. The trend is weak.": "Сигналы большинства индикаторов отрицательные. Тренд слабый.",
  "Hold. The signals of the indicators are conflicting.": "Держать. Сигналы индикаторов разноречивые.",
  "Error loading data": "Ошибка загрузки данных",
  "Enter a valid weight value (0-100%)": "Введите корректное значение веса (0-100%)",
  "Select at least one security with a loaded price": "Выберите хотя бы одну бумагу с загруженной ценой",
  "The following securities have no price loaded": "У следующих бумаг не загружена цена",
  "Please wait for the price to load or click (Details) button to load": "Подождите загрузки или нажмите (Детали) для загрузки",
  "Error calculating portfolio": "Ошибка расчета портфеля",
  "pcs": "шт",
  "Until": "До",
  "RSI (Relative Strength Index)": "RSI (Индекс относительной силы)",  // RSI
  "Measures the strength and speed of price changes. Shows whether the asset is overbought or oversold.": "Измеряет силу и скорость изменения цены. Показывает, перекуплен ли актив или перепродан.",
  "Buy": "Покупка",
  "Neutral": "Нейтрально",
  "Sell": "Продажа",
  "The asset is oversold. Possible upward correction. Consider buying.": "Актив перепродан. Возможна коррекция вверх. Рассмотрите покупку.",
  "The asset is in the lower part of the range. Potential growth.": "Актив в нижней части диапазона. Возможен рост.",
  "The asset is in the upper part of the range. Possible correction.": "Актив в верхней части диапазона. Возможна коррекция.",
  "The asset is overbought. Possible downward correction. Consider selling.": "Актив перекуплен. Возможна коррекция вниз. Рассмотрите продажу.",
  "MACD (Moving Average Convergence Divergence)": "MACD (Схождение-Расхождение Скользящих Средних)",  // MACD
  "Shows the relationship between two moving averages of price. Helps identify trends and reversal points.": "Показывает взаимосвязь между двумя скользящими средними цены. Помогает определить тренд и моменты разворота.",
  "MACD is above zero and rising. Bullish trend. Consider buying.": "MACD выше нуля и растет. Бычий тренд. Рассмотрите покупку.",
  "MACD is below zero and falling. Bearish trend. Consider selling.": "MACD ниже нуля и падает. Медвежий тренд. Рассмотрите продажу.",
  "MACD crossed the signal line upward. Bullish signal.": "MACD пересек сигнальную линию снизу вверх. Бычий сигнал.",
  "MACD crossed the signal line downward. Bearish signal.": "MACD пересек сигнальную линию сверху вниз. Медвежий сигнал.",
  "Bollinger Bands": "Полосы Боллинджера",  // Bollinger Bands
  "Indicates volatility and potential support/resistance levels.": "Показывают волатильность и возможные уровни поддержки/сопротивления.",
  "Price touched the lower band. Possible rebound upward.": "Цена коснулась нижней полосы. Возможен отскок вверх.",
  "Price touched the upper band. Possible pullback downward.": "Цена коснулась верхней полосы. Возможен отскок вниз.",
  "Price is in the middle of the band. Trend continues.": "Цена находится в середине диапазона. Тренд продолжается.",
  "EMA (Exponential Moving Average)": "EMA (Экспоненциальная скользящая средняя)", // EMA
  "Exponential moving average, more sensitive to recent prices.": "Экспоненциальная скользящая средняя, более чувствительна к последним ценам.",
  "Price is above EMA. Uptrend.": "Цена выше EMA. Восходящий тренд.",
  "Price is below EMA. Downtrend.": "Цена ниже EMA. Нисходящий тренд.",
  "ADX (Average Directional Index)": "ADX (Средний направленный индекс)", // ADX
  "Measures the strength of a trend, but not its direction.": "Измеряет силу тренда, но не его направление.",
  "Strong trend": "Сильный тренд",
  "Weak trend": "Слабый тренд",
  "ADX is above 25. Strong trend. Follow the trend.": "ADX выше 25. Тренд сильный. Следуйте тренду.",
  "ADX is below 25. Weak or sideways trend. Be careful.": "ADX ниже 25. Тренд слабый или боковой. Будьте осторожны.",
  "Insufficient data": "Недостаточно данных",
  "Insufficient data for analysis": "Недостаточно данных для анализа",
  "Consider buying": "Рассмотреть покупку",
  "Consider selling": "Рассмотреть продажу",
  "Strong expected loss — possible significant decrease in portfolio value.": "Сильный ожидаемый убыток. Возможное значительное падение стоимости портфеля.",
  "Moderate expected loss — probable decrease in portfolio value.": "Умеренный ожидаемый убыток. Вероятно снижение стоимости портфеля.",
  "Small decrease — within normal volatility.": "Небольшое снижение. В пределах нормальной волатильности.",
  "Stability — portfolio, probably, will maintain the current value.": "Стабильность. Портфель, вероятно, сохранит текущую стоимость.",
  "Moderate growth — positive dynamics.": "Ожидается умеренный рост. Позитивная динамика.",
  "Strong expected growth — possible high yield.": "Сильный ожидаемый рост. Возможная высокая доходность.",
};


const moexIndexes = {
  "Индекс МосБиржи": "MOEX Index",
  "Индекс МосБиржи 10": "MOEX Index 10",
  "Индекс РТС": "RTS Index",
  "Индекс голубых фишек": "Blue Chips Index",
  "Агрессивный индекс": "Aggressive Index",
  "Сбалансированный индекс": "Balanced Index",
  "Индекс МосБиржи (все сессии)": "MOEX Index (All Sessions)",
  "Индекс МосБиржи ЦД-2035": "MOEX Index CD-2035",
  "Индекс МосБиржи ЦД-2040": "MOEX Index CD-2040",
  "Индекс широкого рынка": "Broad Market Index",
  "Субиндекс акций": "Subindex of Stocks",
  "Индекс МосБиржи ЦД-2045": "MOEX Index CD-2045",
  "Индекс MRRT": "MRRT Index",
  "Индекс MRSV": "MRSV Index",
  "Индекс МосБиржи-РСПП MRSV RU Co": "MOEX-RSPP MRSV RU Co Index",
  "Индекс МосБиржи 15": "MOEX Index 15",
  "Индекс Мосбиржи Климатический": "MOEX Climate Index",
  "Консервативный индекс": "Conservative Index",
  "Индекс Мосбиржи гос обл RGBI": "MOEX Government Bonds RGBI",
  "Индекс МосБиржи гос обл RGBITR": "MOEX Government Bonds Total Return RGBITR",
  "Индекс МосБиржи-RAEX ESG": "MOEX-RAEX ESG Index",
  "Индекс нефти и газа": "Oil & Gas Index",
  "Индекс финансов": "Financial Index",
  "Индекс МосБиржи Исламский": "MOEX Islamic Index",
  "Субиндекс облигаций ОФЗ": "OFZ Bonds Subindex",
  "Нац. индекс корп. Управления": "National Corporate Governance Index",
  "Индекс МосБиржи SMID": "MOEX SMID Index",
  "Индекс металлов и добычи": "Metals & Mining Index",
  "Индекс МосБиржи в юанях": "MOEX Index in CNY",
  "Субиндекс корп. флоатеров": "Corporate Floaters Subindex",
  "Индекс потребительского сектора / Индекс потребит сектора": "Consumer Sector Index",
  "Индекс МосБиржи IT": "MOEX IT Index",
  "Индекс Мосбиржи гос обл RGBITR": "MOEX Government Bonds Total Return RGBITR Index"
};



function translate(text) {
  // lang global from html
  if (lang === 'en') return text; // если английский, возвращаем оригинал
  const entry = TRANSLATIONS[text];
  if (!entry) return text; // если перевод не найден, возвращаем оригинал
  return entry;  // если перевод на выбранный язык есть — возвращаем, иначе оригинал
}

function transliteration(text) {
  if (lang === 'ru') return text;
  const map = {
      'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
      'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
      'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch',
      'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
      'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh','З':'Z',
      'И':'I','Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R',
      'С':'S','Т':'T','У':'U','Ф':'F','Х':'Kh','Ц':'Ts','Ч':'Ch','Ш':'Sh','Щ':'Shch',
      'Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya'
  };
  return text.split('').map(char => map[char] || char).join('');
}


// Event Listeners
calculateBtn.addEventListener("click", calculatePortfolio);
attachDisclaimerTooltip(calculateBtn);
if (modalClose) {
	modalClose.addEventListener("click", () => {
		securityModal.classList.add("hidden");
	});
}
if (securityModal) {
	securityModal.addEventListener("click", (e) => {
		if (e.target === securityModal) {
			securityModal.classList.add("hidden");
		}
	});
}

function smoothScroll(event, idx) {
	event.preventDefault();
	document.querySelector(`#${idx}`).scrollIntoView({
		behavior: "smooth"
	});
}

function plural(number, one, few, many) {
	const n = Math.abs(number) % 100;
	const n1 = n % 10;

	if (n > 10 && n < 20) return many;
	if (n1 > 1 && n1 < 5) return few;
	if (n1 === 1) return one;
	return many;
}

// Initialize
loadIndexes();

function updateIndexesCount(count) {
	indexesListCount.forEach((countText) => {
		countText.textContent = count;
	});
}

function updateIndexesCountPlural(count) {
  if (indexesListCountPlural && lang !== 'ru') {
    indexesListCountPlural.textContent = `${count} indices`;
    return;
  }
	if (indexesListCountPlural) {
		indexesListCountPlural.textContent = plural(
			count,
			"индекс",
			"индекса",
			"индексов",
		);
	}
}

function updateSecuritiesCount(count) {
	securitiesListCount.forEach((countText) => {
		countText.textContent = count;
	});
}

function updateSecuritiesCountPlural(count) {
  if (securitiesListCountPlural && lang !== 'ru') {
    securitiesListCountPlural.textContent = `${count} securities`;
    return;
  }
	if (securitiesListCountPlural) {
		securitiesListCountPlural.textContent = plural(
			count,
			"ценная бумага",
			"ценные бумаги",
			"ценных бумаг",
		);
	}
}

async function loadIndexes() {
	loaderTimeout = setTimeout(showLoading, 150);
	try {
		const response = await fetch(`${API_BASE}/api/indexes`);
		const indexes = await response.json();

		displayIndexes(indexes);
		updateIndexesCount(indexes.length);
		updateIndexesCountPlural(indexes.length);
	} catch (error) {
		console.error("Error loading indexes:", error);
		indexesList.innerHTML = `<p class="error-text">${translate("Error loading indexes")}</p>`;
		updateIndexesCount(0);
	} finally {
		clearTimeout(loaderTimeout);
		hideLoading();
	}
}

function createIndexCard(index) {
	const card = document.createElement("div");
	card.className = "index-card transition-all";
	card.style.transition = "all .5s ease";

  const indexName = index.shortname || index.indexid;
	const name = document.createElement("div");
	name.className = "index-name";
	name.textContent = lang === 'ru' ? indexName : (moexIndexes[indexName] || indexName);

	const id = document.createElement("div");
	id.className = "index-id";
	id.textContent = index.indexid;

	card.appendChild(name);
	card.appendChild(id);
	card.dataset.indexid = index.indexid;

	if (index.till) {
		const date = document.createElement("div");
		date.className = "index-date";
		date.textContent = `${'Until'}: ${index.till}`;
		card.appendChild(date);
	}

	function updateCardState() {
		const isSelected = selectedIndexes.some((idx) => idx.indexid === index.indexid);
		if (isSelected) {
			card.classList.add("active-card");
		} else {
			card.classList.remove("active-card");
		}
	}

	updateCardState();

	card.addEventListener("click", async () => {
		const isSelected = selectedIndexes.some(
			(idx) => idx.indexid === index.indexid
		);

		if (isSelected) {
			// Повторный клик на выбранный индекс
			if (selectedIndexes.length === 1) {
				alert(translate("At least one index must be selected"));
				return;
			}
			// Показываем модал для выбора действия
			removeIndex(index.indexid);
		} else {
			// Первый клик или добавление нового
			if (selectedIndexes.length >= MAX_INDEXES) {
				alert(`${translate("You can select a maximum of")} ${MAX_INDEXES} ${translate("indices")}`);
				return;
			}
			// Добавляем индекс
			if (selectedIndexes.length > 0) {
				showIndexActionModal(index, updateCardState);
			} else {
				await addIndex(index.indexid, index.shortname || index.indexid);
				updateCardState();
			}
		}
	});

	return card;
}

function displayIndexes(indexes) {
	indexesList.innerHTML = "";

	if (indexes.length === 0) {
		indexesList.innerHTML = `<p class="error-text">${translate("Indexes not found")}</p>`;
		return;
	}

	indexes.forEach((index) => {
		const card = createIndexCard(index);
		indexesList.appendChild(card);
	});
}

// Функции для работы с множественными индексами
async function addIndex(indexid, indexName) {
	loaderTimeout = setTimeout(showLoading, 150);
	try {
		const response = await fetch(`${API_BASE}/api/index/${indexid}/securities`);
		const securities = await response.json();

		selectedIndexes.push({
			indexid: indexid,
			name: indexName,
			securities: securities,
		});

		await mergeAndDisplayIndexes();
		showSecurities();
	} catch (error) {
		console.error("Error loading securities:", error);
		alert(`${translate("Error loading securities")}`);
	} finally {
		clearTimeout(loaderTimeout);
		hideLoading();
	}
}

function removeIndex(indexid) {
	selectedIndexes = selectedIndexes.filter((idx) => idx.indexid !== indexid);
	mergeAndDisplayIndexes();
	// Обновляем состояние карточек
	document.querySelectorAll(".index-card").forEach((card) => {
		const cardIndexId = card.dataset.indexid;
		const isSelected = selectedIndexes.some(
			(idx) => idx.indexid === cardIndexId
		);
		card.classList.toggle("active-card", isSelected);
	});
}

async function replaceIndexes(indexid, indexName) {
	selectedIndexes = [];
	await addIndex(indexid, indexName);
}

function showIndexActionModal(index, callback) {
	const template = document.querySelector("#index-action-modal-template");
	const clone = template.content.cloneNode(true);
	const modal = clone.querySelector("div");

	modal.querySelector(".index-action-add-btn").addEventListener("click", async () => {
		modal.remove();
		await addIndex(index.indexid, index.shortname || index.indexid);
		callback();
	});

	modal.querySelector(".index-action-replace-btn").addEventListener("click", async () => {
		modal.remove();
		await replaceIndexes(index.indexid, index.shortname || index.indexid);
		// Обновляем состояние карточек
		document.querySelectorAll(".index-card").forEach((card) => {
			const cardIndexId = card.dataset.indexid;
			const isSelected = selectedIndexes.some(
				(idx) => idx.indexid === cardIndexId
			);
			card.classList.toggle("active-card", isSelected);
		});
	});


	modal.querySelectorAll(".index-action-modal-close").forEach((btn) => {
		btn.addEventListener("click", () => modal.remove());
	});

	document.body.appendChild(modal);
	modal.classList.remove("hidden");
}

async function mergeAndDisplayIndexes() {
	if (selectedIndexes.length === 0) {
		currentSecurities = [];
		displaySecurities([]);
		return;
	}

	// Объединяем бумаги: для каждой бумаги берем максимальный вес
	const mergedSecurities = {}; // {secid: {secid, secname, weight, ...}}
	let totalWeight = 0;
	excludedCount = 0;

	selectedIndexes.forEach((indexData) => {
		indexData.securities.forEach((sec) => {
			const secid = sec.secids || sec.SECID || sec.secid || sec.ticker || "";
			const weight = parseFloat(sec.weight || sec.WEIGHT || 0);

			if (!mergedSecurities[secid]) {
				mergedSecurities[secid] = {
					secid: secid,
					secname: sec.shortnames || sec.SECNAME || sec.secname || secid,
					weight: weight,
					originalWeight: weight,
				};
			} else {
				// Берем максимальный вес (не суммируем!)
				mergedSecurities[secid].weight = Math.max(
					mergedSecurities[secid].weight,
					weight
				);
				mergedSecurities[secid].originalWeight = Math.max(
					mergedSecurities[secid].originalWeight,
					weight
				);
			}
		});
	});

	// Фильтруем по минимальному весу
	const filteredSecurities = [];
	Object.values(mergedSecurities).forEach((sec) => {
		if (sec.weight >= MIN_WEIGHT_THRESHOLD || selectedIndexes.length === 1) {
			filteredSecurities.push(sec);
			totalWeight += sec.weight;
		} else {
			excludedCount++;
		}
	});

	// Нормализуем к 100%
	filteredSecurities.forEach((sec) => {
		sec.weight = (sec.weight / totalWeight) * 100;
	});

	// Обновляем заголовок с информацией об исключенных
	if (selectedIndexes.length > 1) {
		const indexNames = selectedIndexes.map((idx) => (lang === 'ru' ? idx.name : (moexIndexes[idx.name] || idx.name))).join(", ");
		currentIndexName = `${indexNames} (${selectedIndexes.length} ${translate("indices")})`;
	} else if (selectedIndexes.length === 1) {
		currentIndexName = lang === 'ru' ? selectedIndexes[0].name : (moexIndexes[selectedIndexes[0].name] || selectedIndexes[0].name);
	}

	currentSecurities = filteredSecurities;
	displaySecurities(filteredSecurities);
}

async function loadIndexSecurities(indexid, indexName) {
	// Старая функция для обратной совместимости
	selectedIndexes = [];
	await addIndex(indexid, indexName);
	currentIndexId = indexid;
	currentIndexName = indexName;
}

// Clustering function
function clusterSecurities(securities) {
	const clusters = {
		large: [], // > 5%
		medium: [], // 1-5%
		small: [], // < 1%
	};

	securities.forEach((sec) => {
		const weight = parseFloat(sec.weight || sec.WEIGHT || 0);
		if (weight > 5) {
			clusters.large.push(sec);
		} else if (weight >= 1) {
			clusters.medium.push(sec);
		} else {
			clusters.small.push(sec);
		}
	});

	return clusters;
}

function displaySecurities(securities) {
	if (securities.length === 0) {
		securitiesList.innerHTML = `<p class="error-text">${translate("Securities not found")}</p>`;
		return;
	}

	indexTitle.textContent = currentIndexName;
	if (excludedCount > 0) {
		indexExcludedCount.textContent = `${translate("Excluded")} ${excludedCount} ${translate("securities with weight less than")} ${MIN_WEIGHT_THRESHOLD}%`;
	} else {
		indexExcludedCount.textContent = "";
	}
	securitiesList.innerHTML = "";
	securitiesStepHeader.classList.remove("hidden");
	securitiesStep.classList.remove("hidden");

	updateSecuritiesCount(securities.length);
	updateSecuritiesCountPlural(securities.length);

	// Cluster securities
	const groupContainer = document.createElement("div");
	groupContainer.dataset.group = "weight";
	securitiesList.appendChild(groupContainer);

	const clusters = clusterSecurities(securities);
	const clusterNames = {
		large: `${translate("Large")} (>5%)`,
		medium: `${translate("Medium")} (1-5%)`,
		small: `${translate("Small")} (<1%)`,
	};
	const clusterColors = {
		large: "#83599a",
		medium: "#242392",
		small: "#66579a",
	};

	// Display clusters
	Object.keys(clusters).forEach((clusterKey) => {
		const clusterSecs = clusters[clusterKey];
		if (clusterSecs.length === 0) return;

		// Cluster header
		const clusterHeader = document.createElement("div");
		clusterHeader.className = "cluster-header";
		clusterHeader.innerHTML = `
      <span class="cluster-indicator" style="background: ${clusterColors[clusterKey]}"></span>
      <span class="cluster-name">${clusterNames[clusterKey]}</span>
      <span class="cluster-count">${clusterSecs.length}</span>
    `;
		groupContainer.appendChild(clusterHeader);

		// Cluster container
		const clusterContainer = document.createElement("div");
		clusterContainer.className = "cluster-container";

		clusterSecs.forEach((sec) => {
			const secid = sec.secids || sec.SECID || sec.secid || sec.ticker || "";
			const secname = sec.shortnames || sec.SECNAME || sec.secname || secid;
			const weight = parseFloat(sec.weight || sec.WEIGHT || 0);
			const isSelected = selectedSecurities[secid]?.selected || false;
			const price = selectedSecurities[secid]?.price || 0;

			const item = document.createElement("div");
			item.className = "security-item" + (isSelected ? " selected" : "");
			item.dataset.secid = secid;
			item.style.cursor = "pointer";

			// === Info block ===
			const info = document.createElement("div");
			info.className = "security-info";

			const nameEl = document.createElement("div");
			nameEl.className = "security-name";
			nameEl.textContent = secname;

			const idEl = document.createElement("div");
			idEl.className = "security-id";
			idEl.textContent = secid;

			const priceEl = document.createElement("div");
			priceEl.className = "security-price";
			priceEl.id = `price-${secid}`;
			priceEl.innerHTML = price > 0 ? `${price.toFixed(2)} ₽` :`<span class="loading-price">${translate('Loading')}...</span>`;

			const weightEl = document.createElement("div");
			weightEl.className = "security-weight";
			weightEl.textContent = `${weight.toFixed(2)}%`;

			info.appendChild(nameEl);
			info.appendChild(idEl);
			info.appendChild(priceEl);
			info.appendChild(weightEl);

			const itemButtons = document.createElement("div");
			itemButtons.className = "security-buttons";

			// === Details button (small icon in corner) ===
			const detailsBtn = document.createElement("button");
			detailsBtn.className = "details-btn-icon";
			detailsBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
        </svg>
      `;
			detailsBtn.title = "Детали";

			// === Edit weight button ===
			const editWeightBtn = document.createElement("button");
			editWeightBtn.className = "edit-weight-btn-icon";
			editWeightBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 20h9"></path>
          <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
        </svg>
      `;
			editWeightBtn.title = "Изменить вес";

			// === Mount inside card ===
			itemButtons.appendChild(detailsBtn);
			itemButtons.appendChild(editWeightBtn);
			item.appendChild(itemButtons);
			item.appendChild(info);

			// Card click = toggle selection
			item.addEventListener("click", (e) => {
				// Don't toggle if clicking on details button
				if (e.target.closest(".details-btn-icon")) {
					return;
				}
				toggleSecurity(secid, weight);
				loadSecurityPrice(secid, weight);
			});

			// Details button
			detailsBtn.addEventListener("click", (e) => {
				e.stopPropagation(); // do not trigger card selection
				showSecurityDetails(secid);
			});

			// Edit weight button
			editWeightBtn.addEventListener("click", (e) => {
				e.stopPropagation(); // do not trigger card selection
				showWeightEditModal(secid, secname, weight);
			});

			clusterContainer.appendChild(item);

			// Load price async
			loadSecurityPrice(secid, weight);
		});

		groupContainer.appendChild(clusterContainer);
	});

	// Smooth scroll
	setTimeout(() => {
		securitiesStepHeader.scrollIntoView({
			behavior: "smooth",
			block: "start"
		});
	}, 500);
}

async function loadSecurityPrice(secid, weight) {
	// Если цена уже загружена, не загружаем повторно
	if (selectedSecurities[secid]?.price) {
		return;
	}

	try {
		const response = await fetch(`${API_BASE}/api/security/${secid}`);
		const data = await response.json();

		if (data.error) {
			document.getElementById(`price-${secid}`).innerHTML =
				`<span class="error-price">${translate("Error")}</span>`;
			return;
		}

		const price = parseFloat(data.security?.prevprice || 0);

		// Сохраняем цену
		if (!selectedSecurities[secid]) {
			selectedSecurities[secid] = {
				selected: false,
				weight: weight,
				price: price,
			};
		} else {
			selectedSecurities[secid].price = price;
		}

		// Обновляем UI
		const priceElement = document.getElementById(`price-${secid}`);
		if (priceElement) {
			priceElement.innerHTML = price > 0 ? price.toFixed(2) + " ₽" : "N/A";
		}
	} catch (error) {
		console.error(`Error loading price for ${secid}:`, error);
		const priceElement = document.getElementById(`price-${secid}`);
		if (priceElement) {
			priceElement.innerHTML = `<span class="error-price">${translate("Error")}</span>`;
		}
	}
}

function toggleSecurity(secid, weight) {
	if (!selectedSecurities[secid]) {
		selectedSecurities[secid] = {
			selected: true,
			weight: weight,
			price: selectedSecurities[secid]?.price || 0,
		};
	} else {
		selectedSecurities[secid].selected = !selectedSecurities[secid].selected;
	}

	// Update UI
	const items = document.querySelectorAll(`[data-secid="${secid}"]`);
	if (items.length > 0) {
		items.forEach((el) =>
			el.classList.toggle("selected", selectedSecurities[secid].selected)
		);
	}
}

function changeGroupVisibility(name) {
	const groupContainer = document.querySelector(`[data-group="${name}"]`);
	if (groupContainer) {
		securitiesList
			.querySelectorAll(":scope > div")
			.forEach((el) => el.classList.add("hidden"));
		groupContainer.classList.remove("hidden");
		return true;
	}
	return false;
}

function changeButtonActive(name) {
	const button = document.querySelector(`[data-btn="${name}"]`);
	if (button) {
		button.parentElement.querySelectorAll(":scope > button").forEach((el) => {
			el.classList.replace("bg-violet", "bg-white");
			el.classList.replace("hover:bg-violet-dark", "hover:bg-gray-200");
		});
		button.classList.replace("bg-white", "bg-violet");
		button.classList.replace("hover:bg-gray-200", "hover:bg-violet-dark");
	}
}

function calculateSummary(indicators) {
	// 1) базовые голоса
	const weights = {
		RSI: 2,
		MACD: 2,
		BB: 1,
		EMA: 1
	};
	const base = {
		buy: 0,
		sell: 0,
		neutral: 0
	};
	for (const key of ["RSI", "MACD", "BB", "EMA"]) {
		const rec = indicators[key]?.recommendation;
		if (!rec) continue;
		const w = weights[key] || 1;
		if (rec.action === translate("Buy")) base.buy += w;
		else if (rec.action === translate("Sell")) base.sell += w;
		else base.neutral += w;
	}

	const adx = indicators["ADX"]?.value ?? 0;

	// 2) определяем победителя по базовым голосам
	const maxVote = Math.max(base.buy, base.sell, base.neutral);
	// если ничья — нейтрально
	const winners = [];
	if (base.buy === maxVote) winners.push("buy");
	if (base.sell === maxVote) winners.push("sell");
	if (base.neutral === maxVote) winners.push("neutral");

	if (winners.length > 1) {
		// явный конфликт — neutral
		return {
			action: translate("Neutral"),
			status: "neutral",
			description: translate("Hold. The signals of the indicators are conflicting."),
		};
	}

	const winner = winners[0]; // 'buy' | 'sell' | 'neutral'

	// 3) решаем, сильный ли сигнал (точно / не точно)
	const STRONG_THRESHOLD = 3; // можно подобрать исходя из весов
	const isStrong = adx >= 25 && base[winner] >= STRONG_THRESHOLD;

	// 4) формируем action / status / description согласованно
	if (winner === "buy") {
		return isStrong ?
			{
				action: `${translate("Buy")} (${translate("strong")})`,
				status: "buy_strong",
				description: `${translate("The signals of the majority of indicators are positive. The trend is strong.")}`,
			} :
			{
				action: `${translate("Buy")} (${translate("weak")})`,
				status: "buy_weak",
				description: `${translate("The signals of the majority of indicators are positive. The trend is weak.")}`,
			};
	}

	if (winner === "sell") {
		return isStrong ?
			{
				action: `${translate("Sell")} (${translate("strong")})`,
				status: "sell_strong",
				description: `${translate("The signals of the majority of indicators are negative. The trend is strong.")}`,
			} :
			{
				action: `${translate("Sell")} (${translate("weak")})`,
				status: "sell_weak",
				description: `${translate("The signals of the majority of indicators are negative. The trend is weak.")}`,
			};
	}

	// neutral
	return {
		action: translate("Neutral"),
		status: "neutral",
		description: translate("Hold. The signals of the indicators are conflicting."),
	};
}

async function groupSecurities(name) {
	loaderTimeout = setTimeout(showLoading, 150);
	changeButtonActive(name);
	if (changeGroupVisibility(name)) {
		clearTimeout(loaderTimeout);
		hideLoading();
		return;
	}

	const clusters = {
		RSI: [],
		MACD: [],
		BB: [],
		EMA: [],
		ADX: [],
		Summary: [],
	};

	// Для итогового Summary
	const clusterColor = {
		buy_strong: "#2ecc71", // ярко-зеленый
		buy_weak: "#7bed9f", // светло-зеленый
		sell_strong: "#e74c3c", // ярко-красный
		sell_weak: "#ff7f7f", // светло-красный
		neutral: "#95a5a6", // серый

		// RSI
		oversold: "#2ecc71", // Покупка → зелёный
		neutral_low: "#95a5a6", // Нейтрально → серый
		neutral_high: "#95a5a6", // Нейтрально → серый
		overbought: "#e74c3c", // Продажа → красный

		// MACD
		bullish: "#2ecc71",
		bearish: "#e74c3c",
		crossover_up: "#2ecc71",
		crossover_down: "#e74c3c",

		// BB
		lower_touch: "#2ecc71",
		upper_touch: "#e74c3c",
		middle: "#95a5a6",

		// EMA
		above: "#2ecc71",
		below: "#e74c3c",

		// ADX
		strong: "#3498db", // синий — сила тренда
		weak: "#95a5a6", // серый — слабый тренд
	};

	try {
		for (const sec of currentSecurities) {
			const secid = sec.secids || sec.SECID || sec.secid || sec.ticker || "";
			const weight = parseFloat(sec.weight || sec.WEIGHT || 0);

			const response = await fetch(`${API_BASE}/api/security/${secid}`);
			const data = await response.json();

			if (data.error) {
				alert(`${translate("Error")}: ${data.error}`);
				clearTimeout(loaderTimeout);
				hideLoading();
				return;
			}

			["RSI", "MACD", "BB", "EMA", "ADX"].forEach((key) => {
				const groupContainerKey = document.querySelector(`[data-group="${key}"]`);

				if (!groupContainerKey && data.indicators[key]) {
					const ind = data.indicators[key];
					const status = ind.status || null;
					const rec = ind.recommendation || {};
					const action = rec.action || null;
					const description = rec.description || null;
					const value = ind.value || rec.value || null; // RSI, MACD, BB, EMA, ADX

					if (action == null || description == null || value == null) return;
					clusters[key][status] ??= {
						action,
						description,
						secids: []
					};
					clusters[key][status]["secids"].push({
						secid: secid,
						value: value,
						weight: weight,
					});
				}
			});

			const summary = calculateSummary(data.indicators);

			// Добавляем в clusters
			clusters["Summary"][summary.status] ??= {
				action: summary.action,
				description: summary.description,
				secids: [],
			};
			clusters["Summary"][summary.status].secids.push({
				secid: secid,
				value: null,
				weight: weight,
			});
		}

		// Display clusters
		Object.keys(clusters).forEach((clusterKey) => {
			const clusterStatus = clusters[clusterKey];
			const statuses = Object.keys(clusterStatus);
			if (statuses.length === 0) return;

			const groupContainerKey = document.createElement("div");
			groupContainerKey.className = "hidden";
			groupContainerKey.dataset.group = clusterKey;
			securitiesList.appendChild(groupContainerKey);

			statuses.forEach((status) => {
				const clusterStatusSecs = clusterStatus[status];
				if (!clusterStatusSecs || clusterStatusSecs.secids.length === 0) return;

				const clusterHeader = document.createElement("div");
				clusterHeader.className = "cluster-header";
				clusterHeader.innerHTML = `
          <span class="cluster-indicator" style="background: ${clusterColor[status]}"></span>
          <span data-description="${clusterStatusSecs.action}" class="cluster-name">${translate(clusterStatusSecs.description)}</span>
          <span class="cluster-count">${clusterStatusSecs.secids.length}</span>
        `;
				groupContainerKey.appendChild(clusterHeader);

				// Cluster container
				const clusterContainer = document.createElement("div");
				clusterContainer.className = "cluster-container";

				clusterStatusSecs.secids.forEach((sec) => {
					const item = document.querySelector(`[data-secid="${sec.secid}"]`);
					if (item) {
						const clone = item.cloneNode(true);

						// Card click = toggle selection
						clone.addEventListener("click", (e) => {
							// Don't toggle if clicking on details or edit buttons
							if (
								e.target.closest(".details-btn-icon") ||
								e.target.closest(".edit-weight-btn-icon")
							) {
								return;
							}
							toggleSecurity(sec.secid, sec.weight);
							loadSecurityPrice(sec.secid, sec.weight);
						});

						// Details button
						const detailsBtn = clone.querySelector(".details-btn-icon");
						if (detailsBtn) {
							detailsBtn.addEventListener("click", (e) => {
								e.stopPropagation(); // do not trigger card selection
								showSecurityDetails(sec.secid);
							});
						}

						// Edit weight button
						const editWeightBtn = clone.querySelector(".edit-weight-btn-icon");
						if (editWeightBtn) {
							const secname = sec.secname || sec.secid;
							const weight = sec.value || sec.weight || 0;
							editWeightBtn.addEventListener("click", (e) => {
								e.stopPropagation(); // do not trigger card selection
								showWeightEditModal(sec.secid, secname, weight);
							});
						}

						// Update parameters
						const weightEl = clone.querySelector(".security-weight");
						if (weightEl) {
							if (sec.value) {
								weightEl.textContent = `${sec.value.toFixed(2)}`;
							} else {
								weightEl.textContent = `N/A`;
							}
						}
						clusterContainer.appendChild(clone);
					}
				});

				groupContainerKey.appendChild(clusterContainer);
			});
		});
	} catch (error) {
		console.error("Error grouping securities:", error);
		alert(`${translate("Error loading data")}`);
	} finally {
		clearTimeout(loaderTimeout);
		hideLoading();
	}

	changeGroupVisibility(name);
}

function showWeightEditModal(secid, secname, currentWeight) {
	const template = document.querySelector("#weight-edit-modal-template");
	const clone = template.content.cloneNode(true);
	const modal = clone.querySelector("div");

	modal.querySelector("#weight-edit-secname").textContent = secname;
	modal.querySelector("#weight-edit-current").textContent =
		currentWeight.toFixed(2);
	const input = modal.querySelector("#weight-edit-input");
	input.value = currentWeight.toFixed(2);

	const saveBtn = modal.querySelector(".weight-edit-save-btn");
	saveBtn.addEventListener("click", () => {
		const newWeight = parseFloat(input.value);
		if (isNaN(newWeight) || newWeight < 0 || newWeight > 100) {
			alert(`${translate("Enter a valid weight value (0-100%)")}`);
			return;
		}

		// Пересчитываем веса
		recalculateWeights(secid, newWeight);
		modal.remove();
	});

	modal.querySelectorAll(".weight-edit-modal-close").forEach((btn) => {
		btn.addEventListener("click", () => modal.remove());
	});

	document.body.appendChild(modal);
	modal.classList.remove("hidden");
	input.focus();
	input.select();
}

function recalculateWeights(changedSecid, newWeight) {
	// Находим все бумаги кроме измененной
	const otherSecurities = currentSecurities.filter(
		(sec) => sec.secid !== changedSecid
	);
	const otherTotalWeight = otherSecurities.reduce(
		(sum, sec) => sum + sec.weight,
		0
	);

	if (otherTotalWeight === 0) {
		// Если это единственная бумага, просто устанавливаем вес
		const sec = currentSecurities.find((s) => s.secid === changedSecid);
		if (sec) {
			sec.weight = newWeight;
		}
	} else {
		// Пересчитываем пропорционально
		const remainingWeight = 100 - newWeight;
		const ratio = remainingWeight / otherTotalWeight;

		otherSecurities.forEach((sec) => {
			sec.weight = sec.weight * ratio;
		});

		const changedSec = currentSecurities.find((s) => s.secid === changedSecid);
		if (changedSec) {
			changedSec.weight = newWeight;
		}
	}

	// Обновляем отображение
	displaySecurities(currentSecurities);

	// Обновляем selectedSecurities
	currentSecurities.forEach((sec) => {
		if (selectedSecurities[sec.secid]) {
			selectedSecurities[sec.secid].weight = sec.weight;
		}
	});
}

async function showSecurityDetails(secid) {
	loaderTimeout = setTimeout(showLoading, 150);
	try {
		const response = await fetch(`${API_BASE}/api/security/${secid}`);
		const data = await response.json();

		if (data.error) {
			alert(`${translate("Error")}: ${data.error}`);
			clearTimeout(loaderTimeout);
			hideLoading();
			return;
		}

		// Обновляем цену в selectedSecurities если она еще не загружена
		if (
			selectedSecurities[secid] &&
			!selectedSecurities[secid].price &&
			data.security?.prevprice
		) {
			selectedSecurities[secid].price = parseFloat(data.security.prevprice);
			const priceElement = document.getElementById(`price-${secid}`);
			if (priceElement) {
				priceElement.innerHTML =
					selectedSecurities[secid].price.toFixed(2) + " ₽";
			}
		}

		displaySecurityModal(data);
	} catch (error) {
		console.error("Error loading security:", error);
		alert(`${translate("Error loading data")}`);
	} finally {
		clearTimeout(loaderTimeout);
		hideLoading();
	}
}

function displaySecurityModal(data) {
	const {
		security,
		indicators,
		predictions
	} = data;

	// Клонируем шаблон модалки
	const template = document.querySelector("#security-modal-template");
	const modalClone = template.content.cloneNode(true);
	document.body.appendChild(modalClone);

	const modal = document.querySelector(".fixed.inset-0.z-50");

	// Header
	modal.querySelector("#modal-secname").textContent = security?.secname || security?.secid || "Неизвестно";
	modal.querySelector("#modal-prevprice").textContent = security?.prevprice ? parseFloat(security.prevprice).toFixed(2) + " ₽" : "N/A";

	// Indicators
	if (indicators && !indicators.error) {
		const indicatorsContainer = modal.querySelector("#modalIndicators");
		const indicatorsContent = modal.querySelector("#modalIndicatorsContent");
		indicatorsContainer.classList.remove("hidden");
		renderIndicators(indicators, indicatorsContent);
	}

	// Predictions
	if (predictions && predictions.length > 0) {
		const predictionsContainer = modal.querySelector("#modalPredictions");
		const predictionsContent = modal.querySelector("#modalPredictionsContent");
		predictionsContainer.classList.remove("hidden");
		renderPredictions(predictions, predictionsContent);
	}

	modal.classList.remove("hidden");

	// Закрытие
	modal.querySelector("#modalClose").onclick = () => modal.remove();

	// Load Dividends, Coupons, Yields
	loadModalDividends(security?.secid);
	loadModalCoupons(security?.secid);
	loadModalYields(security?.secid);
}

function renderIndicators(indicators, container) {
	container.innerHTML = "";
	const template = document.querySelector("#indicator-template");

	["RSI", "MACD", "BB", "EMA", "ADX"].forEach((key) => {
		if (indicators[key]) {
			const ind = indicators[key];
			const rec = ind.recommendation || {};

			const clone = template.content.cloneNode(true);
			clone.querySelector('[data-key="name"]').textContent = translate(ind.info?.name || key);
			clone.querySelector('[data-key="value"]').textContent = ind.value || ind.macd || ind.current_price || "N/A";

			if (rec.action) {
				const recDiv = clone.querySelector('[data-key="recommendation"]');
				recDiv.classList.remove("hidden");
				recDiv.querySelector('[data-key="action"]').textContent = translate(rec.action);
				if (rec.description) {
					recDiv.querySelector('[data-key="description"]').textContent = translate(rec.description);
				}

				// Динамические классы
				const recClass = rec.action.toLowerCase().includes("buy") ?
					"bg-green-400/10 text-green-400 border-green-400/20" :
					rec.action.toLowerCase().includes("sell") ?
					"bg-red-400/10 text-red-400 border-red-400/20" :
					"bg-yellow-400/10 text-yellow-400 border-yellow-400/20";
				recDiv.className = `text-xs border rounded-lg p-2 mt-2 ${recClass}`;
			}

			container.appendChild(clone);
		}
	});
}

function renderPredictions(predictions, container) {
	container.innerHTML = "";
	const template = document.getElementById("prediction-template");

	predictions.forEach((pred) => {
		const clone = template.content.cloneNode(true);
		clone.querySelector('[data-key="date"]').textContent = new Date(pred.date).toLocaleDateString(lang === 'ru' ? "ru-RU" : "en-US");
		clone.querySelector('[data-key="price"]').textContent = pred.price.toFixed(2) + " ₽";
		container.appendChild(clone);
	});
}

async function loadTable(
	templateId,
	containerId,
	data,
	keysToShow = ["date", "sum", "rate"]
) {
	const container = document.querySelector(`#${containerId}`);
	if (!data || !data.length) return;

	const table = document.createElement("div");
	table.innerHTML = `<table class="w-full text-white"><thead></thead><tbody></tbody></table>`;
	const tbody = table.querySelector("tbody");

	data.forEach((item) => {
		const rowTemplate = document.querySelector(`#${templateId}`);
		const row = rowTemplate.content.cloneNode(true);
		keysToShow.forEach((key) => {
			const td = row.querySelector(`[data-key="${key}"]`);
			if (td) {
				if (item[key] !== undefined) {
					td.textContent = item[key];
					td.classList.remove("hidden");
				} else {
					td.classList.add("hidden");
				}
			}
		});
		tbody.appendChild(row);
	});

	//container.innerHTML = '';
	container.appendChild(table);
}

async function loadModalDividends(secid) {
	if (!secid) return;
	try {
		const resp = await fetch(`${API_BASE}/api/security/${secid}/dividends`);
		const dividends = await resp.json();
		if (dividends?.length) {
			const data = dividends.map((d) => ({
				date: d.registryclosedate || d.dividenddate || "N/A",
				sum: d.value || d.dividend || "N/A",
			}));
			loadTable("securities-item-template", "modalDividends", data, [
				"date",
				"sum",
			]);
		} else {
			document.querySelector(`#modalDividends`).classList.add("hidden");
		}
	} catch (e) {}
}

async function loadModalCoupons(secid) {
	if (!secid) return;
	try {
		const resp = await fetch(`${API_BASE}/api/security/${secid}/coupons`);
		const coupons = await resp.json();
		if (coupons?.length) {
			const data = coupons.map((c) => ({
				date: c.coupondate || "N/A",
				sum: c.value || c.couponvalue || "N/A",
				rate: c.rate || c.couponpercent || "N/A",
			}));
			loadTable("securities-item-template", "modalCoupons", data, [
				"date",
				"sum",
				"rate",
			]);
		} else {
			document.querySelector(`#modalCoupons`).classList.add("hidden");
		}
	} catch (e) {}
}

async function loadModalYields(secid) {
	if (!secid) return;
	try {
		const resp = await fetch(`${API_BASE}/api/security/${secid}/yields`);
		const yields = await resp.json();
		if (yields?.length) {
			const data = yields.map((y) => ({
				date: y.tradedate || "N/A",
				sum: y.yieldtooffer || y.yield || "N/A",
			}));
			loadTable("securities-item-template", "modalYields", data, [
				"date",
				"sum",
			]);
		} else {
			document.querySelector(`#modalYields`).classList.add("hidden");
		}
	} catch (e) {}
}

async function calculatePortfolio() {
	const capital = parseFloat(capitalInput.value);

	if (!capital || capital <= 0) {
		alert("Введите корректную сумму капитала");
		return;
	}

	portfolioCapital = capital;

	const selected = Object.entries(selectedSecurities)
		.filter(([_, data]) => data.selected && data.price > 0) // Только с загруженной ценой
		.map(([secid, data]) => ({
			secid: secid,
			weight: data.weight,
			price: data.price,
		}));

	if (selected.length === 0) {
		alert(`${translate("Select at least one security with a loaded price")}`);
		return;
	}

	// Проверяем что все выбранные бумаги имеют цену
	const withoutPrice = selected.filter((s) => !s.price || s.price <= 0);
	if (withoutPrice.length > 0) {
		alert(
			`${translate("The following securities have no price loaded")}: ${withoutPrice
        .map((s) => s.secid)
        .join(", ")}. ${translate('Please wait for the price to load or click (Details) button to load')}.`
		);
		return;
	}

	loaderTimeout = setTimeout(showLoading, 150);
	try {
		const response = await fetch(`${API_BASE}/api/portfolio/calculate`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json"
			},
			body: JSON.stringify({
				capital: capital,
				securities: selected,
			}),
		});

		const result = await response.json();

		if (result.error) {
			alert("Ошибка: " + result.error);
			clearTimeout(loaderTimeout);
			hideLoading();
			return;
		}

		displayPortfolioResults(result, selected);
		showPortfolio();
	} catch (error) {
		console.error("Error calculating portfolio:", error);
		alert(`${translate("Error calculating portfolio")}`);
	} finally {
		clearTimeout(loaderTimeout);
		hideLoading();
	}
}

function interpretReturn(predictedReturn) {
  const r = predictedReturn; // в процентах

  if (r < -5) {
      return `${translate("Strong expected loss — possible significant decrease in portfolio value.")}`;
  } else if (r < -1) {
      return `${translate("Moderate expected loss — probable decrease in portfolio value.")}`;
  } else if (r < 0) {
      return `${translate("Small decrease — within normal volatility.")}`;
  } else if (r < 1) {
      return `${translate("Stability — portfolio, probably, will maintain the current value.")}`;
  } else if (r < 5) {
      return `${translate("Moderate growth — positive dynamics.")}`;
  } else {
      return `${translate("Strong expected growth — possible high yield.")}`;
  }
}


function displayPortfolioResults(result, selected) {
	const {
		capital,
		portfolio_value,
		expected_yield
	} = result;

	document.querySelector("#portfolio-capital").textContent = capital.toLocaleString(lang === 'ru' ? "ru-RU" : "en-US") + " ₽"; // en-US
	document.querySelector("#portfolio-value").textContent = portfolio_value.toLocaleString(lang === 'ru' ? "ru-RU" : "en-US") + " ₽"; // en-US
  document.querySelector("#portfolio-description").textContent = interpretReturn(expected_yield);


	const yieldEl = document.querySelector("#portfolio-yield");
	const yieldElParent = yieldEl.parentElement;
	yieldEl.textContent =
		(expected_yield >= 0 ? "+" : "") + expected_yield.toFixed(2) + "%";
	yieldEl.className = `text-2xl font-bold ${
    expected_yield >= 0 ? "text-green-400" : "text-red-400"
  }`;
	if (expected_yield > 0) {
		yieldElParent.style.background = "rgba(74, 222, 128, 0.10)"; // green-400 /10
	} else if (expected_yield < 0) {
		yieldElParent.style.background = "rgba(248, 113, 113, 0.10)"; // red-400 /10
	} else {
		yieldElParent.style.background = "#1e1e1e8f"; // нейтральный вариант
	}

	const tbody = document.querySelector("#portfolioResults tbody");
	tbody.innerHTML = ""; // очищаем старые строки

	const totalWeight = selected.reduce((sum, s) => sum + s.weight, 0);
	const template = document.getElementById("portfolio-item-template");

	selected.forEach((sec) => {
		const weight = sec.weight / totalWeight;
		const allocation = Math.floor((capital * weight) / sec.price) * sec.price;
		const shares = Math.floor((capital * weight) / sec.price);

		const clone = template.content.cloneNode(true);
		clone.querySelector('[data-key="secid"]').textContent = sec.secid;
		clone.querySelector('[data-key="weight"]').textContent = (weight * 100).toFixed(2) + "%";
		clone.querySelector('[data-key="price"]').textContent = sec.price.toFixed(2) + " ₽";
		clone.querySelector('[data-key="allocation"]').textContent = allocation.toLocaleString(lang === 'ru' ? "ru-RU" : "en-US") + " ₽"; // en-US
		clone.querySelector('[data-key="shares"]').textContent = shares + ` ${translate("pcs")}.`;

		tbody.appendChild(clone);
	});
}

function showIndexes() {
	indexesStep.classList.remove("hidden");
	indexesStep.classList.add("active");
	securitiesStep.classList.add("hidden");
	portfolioStepHeader.classList.add("hidden");
	portfolioStep.classList.add("hidden");
	// Скроллим вверх к индексам
	setTimeout(() => {
		indexesStep.scrollIntoView({
			behavior: "smooth",
			block: "start"
		});
	}, 100);
}

function showSecurities() {
	indexesStep.classList.remove("hidden"); // Показываем оба шага
	securitiesStep.classList.remove("hidden");
	securitiesStep.classList.add("active");
	portfolioStepHeader.classList.add("hidden");
	portfolioStep.classList.add("hidden");
}

function showPortfolio() {
	indexesStep.classList.remove("hidden");
	securitiesStep.classList.remove("hidden");
	portfolioStepHeader.classList.remove("hidden");
	portfolioStep.classList.remove("hidden");
	portfolioStep.classList.add("active");
	// Скроллим к результатам портфеля
	setTimeout(() => {
		portfolioStepHeader.scrollIntoView({
			behavior: "smooth",
			block: "start"
		});
	}, 100);
}

function showLoading() {
	loadingOverlay.classList.add("active");
}

function hideLoading() {
	loadingOverlay.classList.remove("active");
}

function scrollToIndexes() {
	indexesStep.scrollIntoView({
		behavior: "smooth",
		block: "start"
	});
}

function attachDisclaimerTooltip(el) {
	// Для десктопа — tooltip на hover
	el.addEventListener("mouseenter", (e) => {
		if (window.innerWidth < 768) return; // игнор на мобайле
		const template = document.querySelector("#disclaimer-template");
		const clone = template.content.cloneNode(true);
		const tooltip = clone.querySelector("div");
		tooltip.classList.add("tooltip");
		document.body.appendChild(tooltip);
		tooltip.classList.add("show");

		function moveTooltip(ev) {
			tooltip.style.left = ev.pageX + 10 + "px";
			tooltip.style.top = ev.pageY + 10 + "px";
		}

		moveTooltip(e);
		el.addEventListener("mousemove", moveTooltip);

		el.addEventListener(
			"mouseleave",
			() => {
				tooltip.remove();
				el.removeEventListener("mousemove", moveTooltip);
			}, {
				once: true
			}
		);
	});

	// Для мобильных — верхняя плашка один раз за сессию
	el.addEventListener("click", () => {
		if (window.innerWidth >= 768) return; // на десктопе click не нужен
		if (sessionStorage.getItem("disclaimerShown")) return;

		const template = document.querySelector("#disclaimer-template");
		const clone = template.content.cloneNode(true);
		const banner = clone.querySelector("div");

		banner.style.position = "fixed";
		banner.style.top = "0";
		banner.style.left = "50%";
		banner.style.transform = "translateX(-50%)";
		banner.style.width = "90%";
		banner.style.maxWidth = "400px";
		banner.style.zIndex = "9999";

		document.body.appendChild(banner);
		sessionStorage.setItem("disclaimerShown", "true");

		// Автоскрытие через 5 секунд
		setTimeout(() => banner.remove(), 5000);
	});
}

// Make functions available globally
window.loadIndexSecurities = loadIndexSecurities;
window.toggleSecurity = toggleSecurity;
window.showSecurityDetails = showSecurityDetails;
window.showIndexes = showIndexes;
window.showSecurities = showSecurities;
window.scrollToIndexes = scrollToIndexes;
window.loadSecurityPrice = loadSecurityPrice;
window.groupSecurities = groupSecurities;
"use strict";
(() => {
  const themePicker = document.getElementById("website-theme");
  fetch("themes.json", {cache: "no-cache"}).then(response => {
    if (!response.ok) throw new Error("Theme catalog unavailable");
    return response.json();
  }).then(catalog => {
    const api = window.MellipiSiteTheme;
    if (!api || !Array.isArray(catalog.themes)) throw new Error("Invalid theme catalog");
    const themes = catalog.themes.filter(row => api.valid(row) && typeof row.name === "string" && row.name.length <= 32);
    if (!themes.length || new Set(themes.map(row => row.id)).size !== themes.length) throw new Error("Invalid theme list");
    const current = themes.find(row => row.id === document.documentElement.dataset.theme) || themes.find(row => row.id === catalog.defaultTheme) || themes[0];
    themePicker.replaceChildren(...themes.map(row => {
      const option = document.createElement("option"); option.value = row.id; option.textContent = row.name; return option;
    }));
    api.apply(current);
    themePicker.value = current.id;
    themePicker.disabled = false;
    themePicker.addEventListener("change", () => {
      const selected = themes.find(row => row.id === themePicker.value);
      if (!selected || !api.apply(selected, true)) return;
      document.getElementById("theme-status").textContent = `${selected.name} theme selected.`;
    });
  }).catch(() => {
    themePicker.disabled = true;
    themePicker.setAttribute("title", "Themes could not load. Reload to try again.");
  });
  const webUrl = (value) => {
    if (typeof value !== "string" || !value) return null;
    try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password ? url : null; } catch { return null; }
  };
  const officialUrl = value => {
    const url = webUrl(value);
    if (!url || url.port || url.search || url.hash) return null;
    return url;
  };
  const releaseAsset = value => {
    const url = officialUrl(value);
    return url && url.hostname === "github.com" && /^\/ajavadinezhad\/mellipi-os\/releases\/download\/[A-Za-z0-9._~+-]+\/[A-Za-z0-9._~+-]+$/.test(url.pathname) ? url : null;
  };
  const liveImage = value => {
    if (!value || Array.isArray(value) || typeof value !== "object" || typeof value.secureBoot !== "boolean" || !Number.isSafeInteger(value.bytes) || value.bytes <= 0 || typeof value.sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(value.sha256)) return null;
    const url = releaseAsset(value.url), checksum = releaseAsset(value.checksumUrl), guide = officialUrl(value.guideUrl);
    if (!url || !/\.iso$/i.test(url.pathname) || !checksum || checksum.href === url.href || /\.iso$/i.test(checksum.pathname) || checksum.href.slice(0, checksum.href.lastIndexOf("/")) !== url.href.slice(0, url.href.lastIndexOf("/")) || !guide) return null;
    const githubGuide = guide.hostname === "github.com" && /^\/ajavadinezhad\/mellipi-os\/blob\/[A-Za-z0-9._~+-]+\/docs\/[A-Za-z0-9/._~-]+\.md$/.test(guide.pathname);
    const pagesGuide = guide.hostname === "ajavadinezhad.github.io" && /^\/mellipi-os\/[A-Za-z0-9/._~-]+$/.test(guide.pathname);
    return githubGuide || pagesGuide ? {url, checksum, guide, bytes: value.bytes, sha256: value.sha256.toLowerCase(), secureBoot: value.secureBoot} : null;
  };
  const reveal = (selector, href) => document.querySelectorAll(selector).forEach(element => { element.href = href; element.hidden = false; });
  const pathUrl = (base, path) => {
    if (typeof path !== "string" || !/^[a-zA-Z0-9_./-]+$/.test(path) || path.startsWith("/") || path.split("/").includes("..")) return null;
    return new URL(path, base.href.replace(/\/?$/, "/")).href;
  };
  fetch("site-config.json", {cache: "no-cache"}).then(response => {
    if (!response.ok) throw new Error("Site configuration unavailable");
    return response.json();
  }).then(config => {
    const repository = webUrl(config.repositoryUrl);
    const apt = webUrl(config.aptUrl);
    const release = typeof config.release === "string" && /^\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?$/.test(config.release) ? config.release : "0.1.8";
    document.querySelectorAll("[data-release]").forEach(element => {element.textContent = release;});
    reveal("[data-sources]", `sources/${encodeURIComponent(release)}/manifest.json`);
    if (repository && repository.hostname === "github.com" && /^\/[^/]+\/[^/]+\/?$/.test(repository.pathname)) {
      const url = repository.href.replace(/\/$/, "");
      reveal("[data-repository]", url);
      reveal("[data-download]", `${url}/releases/tag/v${encodeURIComponent(release)}`);
      reveal("[data-guide]", `${url}/blob/main/docs/clean-install-acceptance.md`);
      reveal("[data-issues]", `${url}/issues`);
    }
    // Only a completed, reviewed release is configured here. Missing or invalid
    // image metadata leaves the USB option hidden and APT remains available.
    const image = liveImage(config.liveImage);
    if (image) {
      document.getElementById("install-heading").textContent = "Try Mellipi. Make it yours.";
      document.getElementById("install-overview").textContent = "A minimal Ubuntu 24.04 base with Mellipi as the only desktop. Try the live USB, then choose when and where to install.";
      const size = image.bytes >= 1073741824 ? `${(image.bytes / 1073741824).toFixed(1)} GiB` : `${Math.ceil(image.bytes / 1048576)} MiB`;
      document.getElementById("live-image-meta").textContent = `Ubuntu 24.04 · amd64 · ${size}`;
      document.getElementById("live-image-boot").textContent = image.secureBoot ? "Signed Ubuntu boot chain, tested with UEFI Secure Boot. Firmware compatibility varies." : "Secure Boot must be disabled for this unsigned image.";
      const download = document.getElementById("live-image-download");
      download.href = image.url.href;
      download.dataset.sha256 = image.sha256;
      document.getElementById("live-image-checksums").href = image.checksum.href;
      document.getElementById("live-image-guide").href = image.guide.href;
      document.getElementById("live-image").hidden = false;
    }
    const fingerprint = typeof config.signingFingerprint === "string" ? config.signingFingerprint.replace(/\s/g, "").toUpperCase() : "";
    const installer = apt && pathUrl(apt, config.installerPath);
    if (apt && installer && /^[A-F0-9]{40,64}$/.test(fingerprint)) {
      document.getElementById("install-command").textContent = `curl -fSLo install-update-source.sh '${installer}'\nless install-update-source.sh\nsudo sh install-update-source.sh --url '${apt.href.replace(/\/$/, "")}' --fingerprint ${fingerprint}\nsudo apt install mellipi-desktop`;
      document.getElementById("fingerprint").textContent = fingerprint.match(/.{1,4}/g).join(" ");
      document.getElementById("setup-link").href = installer;
      document.getElementById("repository-status").textContent = "Install the complete desktop on a supported Linux base. Existing Mellipi users can add the same source for updates.";
      document.getElementById("repository-install").hidden = false;
    }
  }).catch(() => {
    document.getElementById("repository-status").textContent = "Repository details could not be loaded. Please reload, or use the installation guide in the project repository.";
  });
  document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
    const text = document.getElementById(button.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      document.getElementById("copy-status").textContent = "Installation commands copied.";
      button.textContent = "Copied";
    } catch {
      document.getElementById("copy-status").textContent = "Could not copy. Select the commands above and copy them manually.";
      button.textContent = "Select commands to copy";
    }
  }));
})();

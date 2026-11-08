// Pinokio : crée l'environnement Python et installe les dépendances (ffmpeg compris).
module.exports = {
  run: [
    {
      method: "shell.run",
      params: {
        venv: "env",
        message: [
          "uv pip install -r requirements.txt -r requirements-local.txt",
          "python mediavior.py --verifier",
        ],
      },
    },
    { method: "notify", params: { html: "MediaVior est installé. Clique sur « Lancer »." } },
  ],
};

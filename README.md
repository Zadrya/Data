# Zadrya Data

The substance dataset used by the [Zadrya](https://github.com/Zadrya/Application) app, and the pipeline that builds it.

The dataset is built from PsychonautWiki, validated against a strict schema, reviewed by hand, signed with Ed25519 and published as a GitHub Release. The app ships with a bundled copy and only downloads a newer one if the user enables it.

**Status:** under development, no release yet.

## Development

```sh
make setup   # install the git hooks, once per clone
make check   # before every commit
make ci      # before opening a pull request
```

## License

Code: GPL-3.0-or-later, see [LICENSE](LICENSE). Data derived from [PsychonautWiki](https://psychonautwiki.org): CC BY-SA 4.0.

{
  description = "Rabatzz - FastAPI Web Application";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python313;

        python-libs = import ./python-libs.nix { inherit pkgs python; };

        nativeBuildInputs = [
          python
        ];

        buildInputs = with python.pkgs; [
          fastapi
          uvicorn
          jinja2
          bcrypt
          python-multipart
          qrcode
          isort
          pyflakes
          orgparse
          python-libs.org-python
          slixmpp
          python-dotenv
          python-axolotl-curve25519
          doubleratchet
          omemo
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          inherit nativeBuildInputs;
          buildInputs =
            buildInputs
            ++ (with pkgs; [
              black
              pyrefly
            ]);
        };

        packages.default = python.pkgs.buildPythonApplication {
          pname = "org-web";
          version = "0.1.0";
          pyproject = true;

          src = ./.;

          nativeBuildInputs = with python.pkgs; [
            hatchling
          ];

          propagatedBuildInputs = buildInputs;

          postInstall = ''
            mkdir -p $out/share/org-web
            cp -r templates $out/share/org-web/ || true
            cp -r static $out/share/org-web/ || true
          '';

          doCheck = false;
          pythonImportsCheck = [ ];
        };
      }
    );
}

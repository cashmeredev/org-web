{ pkgs, python }:
{
  org-python = python.pkgs.buildPythonPackage rec {
    pname = "org-python";
    version = "0.3.2";

    src = pkgs.fetchFromGitHub {
      owner = "honmaple";
      repo = "org-python";
      rev = "v${version}";
      hash = "sha256-OT+C6sPg8XdxURhi8Vk0rDnGqkcjVqe4+t2fqymFShg=";
    };

    pyproject = true;

    nativeBuildInputs = with python.pkgs; [
      hatchling
      hatch-vcs
    ];

    doCheck = false;

    meta = with pkgs.lib; {
      description = "Python library for reading Emacs org-mode files";
      homepage = "https://github.com/honmaple/org-python";
      license = pkgs.lib.licenses.bsd3;
      maintainers = [ ];
    };
  };

}

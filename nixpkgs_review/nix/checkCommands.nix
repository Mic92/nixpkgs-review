{ pkgs ? import <nixpkgs> {} }: {

    checkCommands = with pkgs; writeScriptBin "checkCommands"
        ''
        #!${stdenv.shell}

        ${coreutils}/bin/timeout 5 $1 --help 2>1 > /dev/null

        RESULT=$?

        if [ $RESULT -eq 0 ]; then
            res="succeded"
        elif [ $RESULT -eq 124 ]; then
            res="timed out"
        elif [ $RESULT -eq 126 ]; then
            res="not invokable"
        elif [ $RESULT -eq 127 ]; then
            res="not found"
        else
            res="failed"
        fi

        echo "$(
            ${coreutils}/bin/cat $2 | \
            ${jq}/bin/jq --arg attr $1 --arg res $res '. |= . + [{attribute: $attr, result: $res}]'\
        )" > $2

        '';
}

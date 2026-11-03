ThisBuild / scalaVersion := "2.12.18"
ThisBuild / organization := "nexusrv"
ThisBuild / version := "0.3.0"
Compile / unmanagedSourceDirectories += file(sys.props("nexusrv.vex.source")) / "src" / "main" / "scala"
libraryDependencies ++= Seq(
 "com.github.spinalhdl" %% "spinalhdl-core" % "1.13.0",
 "com.github.spinalhdl" %% "spinalhdl-lib" % "1.13.0",
 compilerPlugin("com.github.spinalhdl" %% "spinalhdl-idsl-plugin" % "1.13.0"),
 "org.yaml" % "snakeyaml" % "1.8")
Compile / run / fork := false
